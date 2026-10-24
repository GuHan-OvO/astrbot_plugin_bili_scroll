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

LIVE_COOLDOWN_SECONDS = 30
"""两次真刷之间的最小间隔。300 秒实测太钝（一轮本身就要一两分钟，等于跑完再罚站五分钟后才能继续），30 秒足够挡住连点。

按钮 disabled 只挡得住「同一个页面没刷新」的情况；真正要防的是**连着刷两个视频**——
每刷一次都是一组真实的 B站 写操作，风控是累积的。所以冷却放在后端，刷新页面也拦得住。
"""


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


def _cooldown_remaining(plugin, now: float | None = None) -> int:
    """距离下次可以真刷还有多少秒。0 表示可以。"""
    state = _state(plugin)
    if state.get("running"):
        return 0
    last = float(state.get("finished_at") or 0) or float(state.get("started_at") or 0)
    if not last:
        return 0
    elapsed = (time.time() if now is None else now) - last
    remaining = LIVE_COOLDOWN_SECONDS - elapsed
    return int(remaining) if remaining > 0 else 0


def start_live(plugin) -> dict:
    """启动一次「真的刷一个」：后台跑一轮，最多 1 个视频。

    走的是主流程 ``_run_proactive``，所以会**真的取片、分析、评价、按配置互动**，
    也会真的写 ``watch_log``。耗时可能 1~3 分钟，因此这里只负责启动，
    结果通过 ``live_status`` 轮询——不然一个 HTTP 请求要挂几分钟。

    三种情况会被拒：上一轮还在跑、距上次刷完不到冷却期、没有事件循环。
    前两种都带 ``retry_after``，前端可以据此倒计时。
    """
    state = _state(plugin)
    if state.get("running"):
        return {"started": False, "reason": "上一次还没跑完", "retry_after": 0}

    remaining = _cooldown_remaining(plugin)
    if remaining > 0:
        return {
            "started": False,
            "reason": f"冷却中，还要等 {remaining} 秒（两次真刷至少隔 {LIVE_COOLDOWN_SECONDS} 秒）",
            "retry_after": remaining,
        }

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
        state["finished_at"] = time.time()
        return {"started": False, "reason": f"没有事件循环：{exc}", "retry_after": 0}
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
        "cooldown_remaining": _cooldown_remaining(plugin),
        "cooldown_total": LIVE_COOLDOWN_SECONDS,
    }


# ---------------------------------------------------------------- 单独测私信 / @

_TEST_ATTR = "_trial_test_state"
TEST_COOLDOWN_SECONDS = 30
"""两个测试按钮共用的冷却。它们都是真实写操作，连点等于刷屏。"""


def _test_state(plugin) -> dict:
    state = getattr(plugin, _TEST_ATTR, None)
    if not isinstance(state, dict):
        state = {"last_at": 0.0, "last_kind": ""}
        setattr(plugin, _TEST_ATTR, state)
    return state


def test_cooldown_remaining(plugin) -> int:
    last = float(_test_state(plugin).get("last_at") or 0)
    if not last:
        return 0
    remaining = TEST_COOLDOWN_SECONDS - (time.time() - last)
    return int(remaining) if remaining > 0 else 0


def _owner(plugin) -> tuple[str, str]:
    """(昵称, mid)。昵称优先 OWNER_BILI_NAME，回退 OWNER_NAME。"""
    mid = str(plugin.config.get("OWNER_MID", "") or "").strip()
    name = str(plugin.config.get("OWNER_BILI_NAME", "") or "").strip()
    if not name:
        name = str(plugin.config.get("OWNER_NAME", "") or "").strip()
    return name, mid


async def send_test_private(plugin) -> dict:
    """给主人发一条测试私信。**真实写操作**。

    私信没有 @ 的复杂度，能直接验证「Cookie 能用 + 私信接口通」。
    """
    name, mid = _owner(plugin)
    if not mid.isdigit():
        return {"ok": False, "kind": "private", "error": "未配置 OWNER_MID（主人 B站 UID）"}

    text = "（来自自检）私信通道正常，这条是测试消息。"
    try:
        ok = await plugin._send_bili_private_message(int(mid), text)
    except Exception as exc:
        return {"ok": False, "kind": "private", "error": f"发送异常：{exc}"}
    return {
        "ok": bool(ok),
        "kind": "private",
        "target_mid": mid,
        "target_name": name,
        "text": text,
        "detail": "" if ok else "发送失败：Cookie 失效、对方关闭私信，或被风控拦截",
    }


async def send_test_mention(plugin) -> dict:
    """在最近看过的一个视频下，发一条带**真 @** 的测试评论。**真实写操作**。

    真 @ 依赖 ``at_name_to_mid`` 映射——只往正文里拼 ``@昵称`` 是纯文本，
    B站 不会解析成提及。这里复用 ``core/mention.py`` 的构造逻辑。
    """
    name, mid = _owner(plugin)
    if not name:
        return {
            "ok": False,
            "kind": "mention",
            "error": "未配置主人 B站昵称（OWNER_BILI_NAME / OWNER_NAME）",
        }

    bvid = ""
    for item in reversed(_watch_entries(plugin)):
        if isinstance(item, dict) and item.get("bvid"):
            bvid = str(item["bvid"])
            break
    if not bvid:
        return {"ok": False, "kind": "mention", "error": "还没有看过的视频，先刷一轮再来测"}

    try:
        oid = await plugin._get_video_oid(bvid)
    except Exception as exc:
        return {"ok": False, "kind": "mention", "error": f"取 oid 失败：{exc}"}
    if not oid:
        return {"ok": False, "kind": "mention", "bvid": bvid, "error": f"拿不到 {bvid} 的 oid"}

    from .mention import build_mention_map, compose_comment

    at_map = build_mention_map(name, mid)
    text = compose_comment("（来自自检）在，能看到这条吗？", name)
    try:
        result = await plugin._send_comment(oid, text, at_name_to_mid=at_map)
    except Exception as exc:
        return {"ok": False, "kind": "mention", "error": f"发送异常：{exc}"}
    return {
        "ok": bool(result),
        "kind": "mention",
        "bvid": bvid,
        "oid": oid,
        "text": text,
        "at_map": at_map,
        "rpid": result if isinstance(result, int) else 0,
        "detail": ""
        if result
        else "发送失败：Cookie 失效、评论区关闭、含敏感词，或被风控拦截（未降级重发，避免多一条评论）",
    }


async def run_test_action(plugin, kind: str) -> dict:
    """统一的测试入口：带冷却，跑完记录时间。

    ``kind`` 取 ``private`` 或 ``mention``；其他值原样报错，不猜。
    """
    if kind not in {"private", "mention"}:
        return {"ok": False, "kind": kind, "error": f"未知的测试类型：{kind}"}

    remaining = test_cooldown_remaining(plugin)
    if remaining > 0:
        return {
            "ok": False,
            "kind": kind,
            "error": f"冷却中，还要等 {remaining} 秒（两个测试共用 {TEST_COOLDOWN_SECONDS} 秒冷却）",
            "retry_after": remaining,
        }

    runner = send_test_private if kind == "private" else send_test_mention
    result = await runner(plugin)
    _test_state(plugin)["last_at"] = time.time()
    return result
