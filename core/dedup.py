"""候选池去重。

两个层次，风险完全不同：

1. **同一个 BV 出现多次**（不同视频池/不同来源返回同一条）——纯收益，永远可以做。
2. **不同 BV、标题高度相似**（同一事件被多个 UP 报道）——要不要合并**取决于使用者**：
   有人嫌重复，也有人想看不同视角。所以只提供机制，由配置开关决定，默认不开。

故意不调 embedding：标题相似度用字符 2-gram 的 Jaccard 就够，
既不用花钱，也能在单测里精确验证。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

DEFAULT_TITLE_THRESHOLD = 0.75
"""标题相似度阈值。故意取高值：宁可漏合并，也不要把两条不同内容删成一条。"""

_BVID_KEYS = ("bvid", "bv")
_TITLE_KEYS = ("title",)
_SCORE_KEYS = ("play", "view", "stat_view")


def _text(value) -> str:
    return str(value or "").strip()


def _first(item: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return ""


def _bvid_of(item: dict) -> str:
    return _text(_first(item, _BVID_KEYS))


def _title_of(item: dict) -> str:
    return _text(_first(item, _TITLE_KEYS))


def _popularity(item: dict) -> float:
    """用于「重复时留哪一条」：优先播放量高（字段名各来源不一致，挨个试）。"""
    for key in _SCORE_KEYS:
        value = item.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"[\s\W_]+", "", text.lower())
    if len(cleaned) < 2:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def title_similarity(a, b) -> float:
    """字符 2-gram 的 Jaccard 相似度，范围 0~1。任一为空串时返回 0。"""
    ga, gb = _bigrams(_text(a)), _bigrams(_text(b))
    if not ga or not gb:
        return 0.0
    union = ga | gb
    return len(ga & gb) / len(union) if union else 0.0


def dedupe_by_bvid(items) -> list:
    """同一个 BV 只留播放量最高的一条；没有 BV 的条目原样保留。

    保持原有顺序（第一次出现的位置），只是换成播放量更高的那份数据。
    """
    rows = [item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
    best: dict[str, int] = {}
    for index, item in enumerate(rows):
        bvid = _bvid_of(item)
        if not bvid:
            continue
        if bvid not in best:
            best[bvid] = index
            continue
        if _popularity(item) > _popularity(rows[best[bvid]]):
            best[bvid] = index

    # 顺序按「首次出现」保留，数据统一换成该 BV 播放量最高的那份
    out = []
    emitted: set[str] = set()
    for item in rows:
        bvid = _bvid_of(item)
        if not bvid:
            out.append(item)  # 没有 BV 的照留，交给后续过滤
            continue
        if bvid in emitted:
            continue
        emitted.add(bvid)
        out.append(rows[best[bvid]])
    return out


def dedupe_similar_titles(
    items, *, threshold: float = DEFAULT_TITLE_THRESHOLD, max_compare: int = 200
) -> list:
    """标题高度相似时只保留播放量最高的那一条。

    贪心做法：按播放量从高到低依次决定，与**已保留**的任一条相似度超过阈值就丢弃。
    这样保留的永远是这一簇里最热的那条，且结果与输入顺序无关。
    """
    rows = [item for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
    if len(rows) <= 1:
        return rows

    threshold = max(0.0, min(1.0, float(threshold)))
    ordered = sorted(rows, key=_popularity, reverse=True)[:max_compare]
    ordered_ids = {id(item) for item in ordered}
    rest = [item for item in rows if id(item) not in ordered_ids]

    kept: list = []
    kept_titles: list[str] = []
    for item in ordered:
        title = _title_of(item)
        if title and any(title_similarity(title, other) >= threshold for other in kept_titles):
            continue
        kept.append(item)
        if title:
            kept_titles.append(title)

    # 超出比较上限的条目原样带回去（不做二次判断，避免 O(n^2) 爆炸）
    return kept + rest
