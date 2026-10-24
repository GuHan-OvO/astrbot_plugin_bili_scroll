"""试运行（干跑）：只做「取片 + 预演」，不做任何写操作。

和正式跑一轮的区别：

- **不点赞、不投币、不收藏、不关注、不发评论**（连一次写请求都没有）
- **不写 watch_log**，跑多少次都不影响历史
- **不调模型**去评视频内容（那要下载和分析，又慢又花钱）

它回答的问题是：「现在它能取到什么片？正式跑的话会动哪些手？」

所以安全、可重复，适合在改完配置之后点一下看看链路通不通。
"""

from __future__ import annotations

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
