"""候选排序：把「今天这几十个候选先看谁」从随机改成按命中度排。

只用本地的三样数据，不联网、不依赖陪伴插件：

- 口味分区：最近一周平均分够高的分区（``_get_taste_tids``）
- 兴趣画像：画像里「多留意」的题材、「少看或不看」的条目（--只有开关打开才读）
- 负向信号：偏好生命周期里 dislike / fatigue 的具体对象

``fav``（收藏夹投喂池）不参与排序——那是用户主动指定的，顺序就是优先级。

设计取向：**只调整顺序，不做过滤**。低分候选仍留在队列里，只是排在后面；
这样即使画像写错，最坏结果也只是这一轮挑得偏，而不是某个题材彻底看不到。
"""

from __future__ import annotations

import hashlib
from typing import Any

# 各项权重。写死在这里而不是做成配置：这些数字决定了排序手感，
# 先跑对照实验定下来再考虑暴露给用户。
WEIGHT_PARTITION = 0.35
"""分区命中「口味分区」。"""

WEIGHT_INTEREST = 0.25
"""标题命中画像里的「多留意」。"""

WEIGHT_UP_LIKE = 0.30
"""UP 主命中偏好的具体对象。"""

PENALTY_DISLIKE = 0.50
"""命中「少看或不看」，以及 dislike 信号。"""

PENALTY_FATIGUE = 0.30
"""命中 fatigue 信号。"""

EXPLORATION_FLOOR = 0.15
"""探索候选的分数下限，避免被负分候选反超。"""


def _exploration_slot(bvid: str, ratio: float) -> bool:
    """与 ``_should_watch_video_before_download`` 里同一套抽签，保证两处判断一致。"""
    slot = int(hashlib.sha256(str(bvid or "").encode()).hexdigest()[:8], 16) / 0x100000000
    return slot < ratio


def build_index(plugin: Any) -> dict[str, Any]:
    """汇总排序需要的数据；任何一项读失败都退化成空集合，不影响刷视频。"""
    index: dict[str, Any] = {
        "tids": set(),
        "tname_to_tid": {},
        "interests": [],
        "negative": set(),
    }
    try:
        index["tids"] = set(plugin._get_taste_tids() or [])
    except Exception:
        index["tids"] = set()
    try:
        index["tname_to_tid"] = dict(plugin._build_tname_to_tid_map() or {})
    except Exception:
        index["tname_to_tid"] = {}

    # 画像里的正/负向题材，只有开关打开才读——关掉时排序退化成「只看口味分区」。
    try:
        if plugin.config.get("TASTE_PROFILE_ENABLE", False):
            from .taste_profile import load_profile

            profile = load_profile(plugin)
            index["interests"] = [
                str(item.get("topic") or "").strip()
                for item in (profile.get("interests") or [])
                if str(item.get("topic") or "").strip()
            ]
            index["negative"].update(
                str(item.get("topic") or "").strip().lower()
                for item in (profile.get("dislikes") or [])
                if str(item.get("topic") or "").strip()
            )
    except Exception:
        pass

    # 生命周期里的负向偏好（dislike / fatigue）按具体对象纳入。
    try:
        for item in plugin._lifecycle_preference_items() or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("polarity") or "") not in {"dislike", "fatigue"}:
                continue
            value = str(item.get("value") or "").strip()
            if value:
                index["negative"].add(value.lower())
    except Exception:
        pass

    return index


def score_video(video: dict[str, Any], index: dict[str, Any]) -> tuple[float, str]:
    """给单个候选打分；返回 ``(分数, 一句理由)``，理由只用于日志。"""
    score = 0.0
    reasons: list[str] = []

    tname = str(video.get("tname") or "").strip()
    if tname and index.get("tids"):
        tid = index.get("tname_to_tid", {}).get(tname)
        if tid and tid in index["tids"]:
            score += WEIGHT_PARTITION
            reasons.append(f"分区:{tname}")

    title = str(video.get("title") or "")
    up_name = str(video.get("up_name") or "")
    haystack = f"{title} {up_name}".lower()

    for topic in index.get("interests") or []:
        if topic and topic.lower() in haystack:
            score += WEIGHT_INTEREST
            reasons.append(f"画像:{topic}")
            break

    for topic in index.get("negative") or set():
        if not topic:
            continue
        if topic in haystack:
            if any(word in topic for word in ("疲劳", "看腻", "厌")):
                score -= PENALTY_FATIGUE
                reasons.append(f"疲劳:{topic}")
            else:
                score -= PENALTY_DISLIKE
                reasons.append(f"避开:{topic}")
            break

    if not reasons:
        return score, ""
    return score, "、".join(reasons)


def rank_candidates(
    candidates: dict[str, list[dict[str, Any]]],
    index: dict[str, Any],
    exploration_ratio: float = 0.3,
) -> dict[str, list[dict[str, Any]]]:
    """按分数重排各来源的候选；``fav`` 保持原顺序。

    排序是稳定的：分数相同就维持原来的相对顺序，避免每轮结果抖动。
    """
    ranked: dict[str, list[dict[str, Any]]] = {}
    for source, items in (candidates or {}).items():
        items = list(items or [])
        if source == "fav" or not items:
            ranked[source] = items
            continue
        decorated = []
        for position, video in enumerate(items):
            score, reason = score_video(video, index)
            if _exploration_slot(str(video.get("bvid") or ""), exploration_ratio):
                video = dict(video)
                video["_exploration"] = True
                score = max(score, EXPLORATION_FLOOR)
                reason = f"{reason}、探索位" if reason else "探索位"
            decorated.append((score, position, video, reason))
        decorated.sort(key=lambda item: (-item[0], item[1]))
        for _score, _position, video, reason in decorated:
            if reason:
                video["_rank_reason"] = reason
        ranked[source] = [item[2] for item in decorated]
    return ranked
