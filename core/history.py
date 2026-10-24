"""历史记录查询：把 ``watch_log.json`` 的条目过滤、分页、统计。

纯函数，不读文件、不碰插件实例 —— 便于单测，也让 ``webui_bridge`` 只负责搬数据。

数据来源是 ``watch_log.json``（``core/config.py`` 的 ``WATCH_LOG_FILE``），
写入侧只保留最近 200 条（``proactive.py`` 的 ``cap=200``），所以「历史」的上限就是 200，
要更久得改写入侧或接 B站 的观看历史接口。
"""

from __future__ import annotations

from typing import Any, Iterable

MAX_LIMIT = 100
"""单页上限，防止前端一次拉太多。"""

_DEFAULT_LIMIT = 24

# 展示用字段：不把 preference_signals / diagnostic 这类长字段塞进列表
_LIST_FIELDS = (
    "time",
    "bvid",
    "title",
    "up_name",
    "up_mid",
    "score",
    "score_reason",
    "mood",
    "comment",
    "review",
    "pic",
    "tname",
    "source",
    "source_detail",
    "manual",
    "content_summary",
    "analysis_basis",
    "recommend_reason",
    "recommended_at",
)


def is_recommended(entry: dict) -> bool:
    """是否真的推荐过给主人（三种渠道任一）。"""
    actions = entry.get("actions")
    if not isinstance(actions, list):
        return False
    return any("推荐给主人" in str(action or "") for action in actions)


def is_failed(entry: dict) -> bool:
    """这一条是不是「评价失败」——失败条目没有可信分数，列表里要能区分出来。"""
    return str(entry.get("evaluation_status") or "") == "failed"


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(text) -> str:
    return str(text or "").strip().lower()


def _matches(entry: dict, *, min_score, max_score, mood, source, recommended, failed, q, since, until) -> bool:
    if min_score is not None or max_score is not None:
        score = _to_float(entry.get("score"))
        if score is None:
            return False
        if min_score is not None and score < min_score:
            return False
        if max_score is not None and score > max_score:
            return False

    if mood and _norm(entry.get("mood")) != _norm(mood):
        return False
    if source and _norm(entry.get("source")) != _norm(source):
        return False
    if recommended is not None and is_recommended(entry) != recommended:
        return False
    if failed is not None and is_failed(entry) != failed:
        return False

    time_text = str(entry.get("time") or "")
    if since and time_text < since:
        return False
    if until and time_text > until:
        return False

    if q:
        needle = _norm(q)
        haystack = " ".join(
            _norm(entry.get(key))
            for key in ("title", "up_name", "comment", "review", "score_reason", "tname")
        )
        if needle not in haystack:
            return False
    return True


def _public_entry(entry: dict) -> dict:
    item = {key: entry.get(key) for key in _LIST_FIELDS}
    item["recommended"] = is_recommended(entry)
    item["failed"] = is_failed(entry)
    # 分数统一成数字，前端不必再判空
    item["score"] = _to_float(entry.get("score")) or 0.0
    return item


def summarize(entries: Iterable[dict], *, today_prefix: str = "") -> dict:
    """给筛选后的结果算几个数字，用于页面顶部概览。"""
    items = list(entries)
    scores = [_to_float(e.get("score")) for e in items]
    scores = [s for s in scores if s is not None and s > 0]
    return {
        "total": len(items),
        "average_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "today": sum(1 for e in items if str(e.get("time") or "").startswith(today_prefix))
        if today_prefix
        else 0,
        "recommended": sum(1 for e in items if is_recommended(e)),
        "failed": sum(1 for e in items if is_failed(e)),
    }


def query_history(
    entries: Any,
    *,
    offset: int = 0,
    limit: int = _DEFAULT_LIMIT,
    min_score=None,
    max_score=None,
    mood: str = "",
    source: str = "",
    recommended: bool | None = None,
    failed: bool | None = None,
    q: str = "",
    since: str = "",
    until: str = "",
    today_prefix: str = "",
) -> dict:
    """过滤 + 排序 + 分页。

    排序按 ``time`` 字符串倒序（格式固定为 ``YYYY-MM-DD HH:MM``，字典序即时间序）。
    """
    rows = [e for e in (entries if isinstance(entries, list) else []) if isinstance(e, dict)]

    filtered = [
        e
        for e in rows
        if _matches(
            e,
            min_score=min_score,
            max_score=max_score,
            mood=mood,
            source=source,
            recommended=recommended,
            failed=failed,
            q=q,
            since=since,
            until=until,
        )
    ]
    filtered.sort(key=lambda e: str(e.get("time") or ""), reverse=True)

    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    # 注意：不能用 `limit or 默认值`——limit=0 是合法输入，意图是「只要 1 条」，
    # 而 `0 or 24` 会静默变成 24。
    try:
        limit = _DEFAULT_LIMIT if limit is None else int(limit)
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(MAX_LIMIT, limit))
    page = filtered[offset : offset + limit]

    return {
        "total": len(filtered),
        "offset": offset,
        "limit": limit,
        "stats": summarize(filtered, today_prefix=today_prefix),
        "items": [_public_entry(e) for e in page],
    }


def find_entry(entries: Any, bvid: str) -> dict | None:
    """按 BV 号取单条（重复出现时取最新那条）。"""
    target = str(bvid or "").strip()
    if not target:
        return None
    rows = [
        e
        for e in (entries if isinstance(entries, list) else [])
        if isinstance(e, dict) and str(e.get("bvid") or "") == target
    ]
    if not rows:
        return None
    rows.sort(key=lambda e: str(e.get("time") or ""), reverse=True)
    latest = rows[0]
    detail = dict(latest)
    detail["recommended"] = is_recommended(latest)
    detail["failed"] = is_failed(latest)
    detail["score"] = _to_float(latest.get("score")) or 0.0
    detail["seen_times"] = len(rows)
    return detail
