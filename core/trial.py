"""试运行（干跑）：只做「取片 + 预演」，不做任何写操作。

和正式跑一轮的区别：

- **不点赞、不投币、不收藏、不关注、不发评论**（连一次写请求都没有）
- **不写 watch_log**，跑多少次都不影响历史
- **不调模型**去评视频内容（那要下载和分析，又慢又花钱）

它回答的问题是：「现在它能取到什么片？正式跑的话会动哪些手？」

所以安全、可重复，适合在改完配置之后点一下看看链路通不通。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from astrbot.api import logger

MAX_CANDIDATES = 5
"""只回前几条，够看口味就行。"""

# 正式跑时会读的动作阈值（默认值与上游一致）
ACTION_THRESHOLDS = (
    ("PROACTIVE_LIKE_MIN_SCORE", 6, "点赞"),
    ("PROACTIVE_COIN_MIN_SCORE", 8, "投币"),
)


def _int_config(plugin, key: str, default: int) -> int:
    try:
        return int(plugin.config.get(key, default))
    except Exception:
        return default


def _bool_config(plugin, key: str, default: bool = True) -> bool:
    try:
        value = plugin.config.get(key, default)
    except Exception:
        return default
    return bool(value)


def _candidate(video: dict) -> dict:
    """把候选裁成展示需要的字段，避免把内部标记（`_source` 等）漏给前端。"""
    return {
        "bvid": video.get("bvid", ""),
        "title": video.get("title", ""),
        "up_name": video.get("up_name", ""),
        "play": video.get("play", video.get("view", "")),
        "duration": video.get("duration", ""),
        "tname": video.get("tname", ""),
        "source": video.get("_source", ""),
        "pic": video.get("pic", ""),
    }


def _plan(plugin) -> dict:
    """按当前配置推演「正式跑会做什么」，只是文字，不执行。"""
    items = []
    for key, default, label in ACTION_THRESHOLDS:
        enabled = _bool_config(plugin, key.replace("_MIN_SCORE", ""), True)
        items.append(
            {
                "action": label,
                "enabled": enabled,
                "threshold": _int_config(plugin, key, default),
                "config_key": key,
            }
        )
    return {
        "actions": items,
        "proactive_enabled": _bool_config(plugin, "ENABLE_PROACTIVE", False),
        "note": "试运行不会执行任何写操作；分数达到阈值才动手，且受每日上限约束。",
    }


async def run_trial(plugin) -> dict:
    """跑一次干跑。任何一步失败都只记录，不抛给调用方。"""
    started = time.monotonic()
    result: dict[str, Any] = {
        "ok": True,
        "cookie": {},
        "candidates": [],
        "candidate_total": 0,
        "plan": _plan(plugin),
        "errors": [],
        "elapsed_ms": 0,
    }

    # 1. 登录态
    try:
        ok, detail = await plugin.check_cookie()
        result["cookie"] = {"ok": bool(ok), "detail": str(detail)}
    except Exception as exc:
        result["cookie"] = {"ok": False, "detail": f"检查失败：{exc}"}
        result["errors"].append(f"cookie: {exc}")

    # 2. 取片（只取，不评价、不互动）
    try:
        videos = await plugin._get_pool_videos()
        if not isinstance(videos, list):
            videos = []
        result["candidate_total"] = len(videos)
        result["candidates"] = [_candidate(v) for v in videos[:MAX_CANDIDATES] if isinstance(v, dict)]
    except Exception as exc:
        logger.warning(f"[BiliBot] 试运行取片失败：{exc}")
        result["errors"].append(f"取片失败：{exc}")

    result["ok"] = not result["errors"]
    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


# ---------------------------------------------------------------- 真跑一条

_STATE_ATTR = "_trial_live_state"


def _state(plugin) -> dict:
    state = getattr(plugin, _STATE_ATTR, None)
    if not isinstance(state, dict):
        state = {
            "running": False,
            "started_at": 0.0,
            "finished_at": 0.0,
            "watched": None,
            "error": "",
        }
        setattr(plugin, _STATE_ATTR, state)
    return state


def _watch_entries(plugin) -> list:
    """读 watch_log。失败当空列表——状态展示不值得把任务搞挂。"""
    try:
        from .config import WATCH_LOG_FILE

        data = plugin._load_json(WATCH_LOG_FILE, [])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _latest_watched(plugin, before: int) -> dict | None:
    """跑完后找出新落进去的那条。没新增说明这一轮没看成。"""
    rows = _watch_entries(plugin)
    if len(rows) <= before:
        return None
    latest = rows[-1]
    if not isinstance(latest, dict):
        return None
    return {
        "bvid": latest.get("bvid", ""),
        "title": latest.get("title", ""),
        "up_name": latest.get("up_name", ""),
        "score": latest.get("score"),
        "mood": latest.get("mood"),
        "comment": latest.get("comment", ""),
        "review": latest.get("review", ""),
        "score_reason": latest.get("score_reason", ""),
        "actions": latest.get("actions", []),
        "time": latest.get("time", ""),
        "failed": str(latest.get("evaluation_status") or "") == "failed",
    }


def start_live(plugin) -> dict:
    """启动一次「真的刷一个」：后台跑一轮，最多 1 个视频。

    走的是主流程 ``_run_proactive``，所以会**真的取片、分析、评价、按配置互动**，
    也会真的写 ``watch_log``。耗时可能 1~3 分钟，因此这里只负责启动，
    结果通过 ``live_status`` 轮询——不然一个 HTTP 请求要挂几分钟。
    """
    state = _state(plugin)
    if state.get("running"):
        return {"started": False, "reason": "上一次还没跑完"}

    before = len(_watch_entries(plugin))
    state.update(
        {
            "running": True,
            "started_at": time.time(),
            "finished_at": 0.0,
            "watched": None,
            "error": "",
        }
    )

    async def runner() -> None:
        try:
            await plugin._run_proactive(max_watch=1)
        except Exception as exc:  # _run_proactive 自己会吞，这里是双保险
            state["error"] = str(exc)
        finally:
            state["watched"] = _latest_watched(plugin, before)
            state["running"] = False
            state["finished_at"] = time.time()

    try:
        asyncio.get_running_loop().create_task(runner())
    except RuntimeError as exc:
        state["running"] = False
        return {"started": False, "reason": f"没有事件循环：{exc}"}
    return {"started": True}


def live_status(plugin) -> dict:
    """当前真跑状态。running 为假时 elapsed_ms 是本次总耗时。"""
    state = _state(plugin)
    started_at = float(state.get("started_at") or 0)
    finished_at = float(state.get("finished_at") or 0)
    running = bool(state.get("running"))
    end = time.time() if running else finished_at
    elapsed = max(0, int((end - started_at) * 1000)) if started_at else 0
    return {
        "running": running,
        "elapsed_ms": elapsed,
        "watched": state.get("watched"),
        "error": state.get("error") or "",
        "finished_at": finished_at,
    }
