"""用量与成本台账。

## 为什么要有这个

插件里 `MEDIA_TOKEN_BUDGET_DAILY` 只是个**上限**，从来没记过实际花了多少。
`stats` 路由能看到「今天回复了几条」，但看不到「今天烧了多少 token、哪个环节最贵、
提示词缓存到底生效没有」。没有这本账，调档位、加视频池、换模型全是凭感觉。

## 数据来源

AstrBot 的 `LLMResponse.usage` 是 `TokenUsage`，含三段：

- `input_other`  —— 未命中缓存的输入
- `input_cached` —— 命中提示词缓存的输入（单价通常低一个数量级，值得单独记）
- `output`       —— 输出

OpenAI 兼容 provider 会填这个字段（`stream_options={"include_usage": True}`）；
拿不到时记 0，但**仍然记这一条调用**——次数本身也是成本信号。

## 存储

``usage_log.jsonl``，一行一条，追加写：

```json
{"ts": 1793000000.0, "day": "2026-10-25", "purpose": "GENERATION",
 "model": "deepseek-chat", "in": 1200, "cached_in": 800, "out": 300,
 "media_cached": false}
```

按天裁剪（默认保留 30 天），读的时候顺手裁。写失败绝不影响主流程——账本不能把业务搞挂。
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable

KEEP_DAYS = 30
"""账本保留天数。一天几百行，不占地方。"""


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def make_entry(
    *,
    purpose: str,
    model: str = "",
    input_other: int = 0,
    input_cached: int = 0,
    output: int = 0,
    media_cached: bool = False,
    now: float | None = None,
) -> dict:
    """组装一条记录。纯函数，便于测试。"""
    ts = time.time() if now is None else float(now)
    return {
        "ts": round(ts, 3),
        "day": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
        "purpose": str(purpose or "chat"),
        "model": str(model or "")[:80],
        "in": max(0, int(input_other or 0)),
        "cached_in": max(0, int(input_cached or 0)),
        "out": max(0, int(output or 0)),
        "media_cached": bool(media_cached),
    }


def _sum(entries: Iterable[dict]) -> dict:
    calls = 0
    input_other = input_cached = output = 0
    marked = media_hits = 0
    for item in entries:
        calls += 1
        input_other += int(item.get("in", 0) or 0)
        input_cached += int(item.get("cached_in", 0) or 0)
        output += int(item.get("out", 0) or 0)
        if "media_cached" in item:
            marked += 1
            if item.get("media_cached"):
                media_hits += 1
    total_in = input_other + input_cached
    return {
        "calls": calls,
        "input_other": input_other,
        "input_cached": input_cached,
        "output": output,
        "total_input": total_in,
        "total_tokens": total_in + output,
        # 缓存命中率只对「有输入」的调用有意义
        "cache_hit_ratio": round(input_cached / total_in, 4) if total_in else 0.0,
        "media_cache_hits": media_hits,
        "media_cache_total": marked,
        "media_cache_hit_ratio": round(media_hits / marked, 4) if marked else 0.0,
    }


def _group(entries: list[dict], key: str) -> dict:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in entries:
        buckets[str(item.get(key) or "unknown")].append(item)
    return {name: _sum(items) for name, items in sorted(buckets.items())}


def summarize(entries: Iterable[dict], *, days: int = 1, budget: int = 0, now: float | None = None) -> dict:
    """把记录聚合成一页能看的东西。纯函数。"""
    rows = [e for e in entries if isinstance(e, dict)]
    now_ts = time.time() if now is None else float(now)
    since = now_ts - max(1, int(days)) * 86400
    window = [e for e in rows if float(e.get("ts", 0) or 0) >= since]

    daily_buckets: dict[str, list[dict]] = defaultdict(list)
    for item in window:
        daily_buckets[str(item.get("day") or "unknown")].append(item)

    today = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d")
    today_stats = _sum(daily_buckets.get(today, []))
    window_stats = _sum(window)

    result = {
        "days": max(1, int(days)),
        "window": window_stats,
        "today": today_stats,
        "by_purpose": _group(window, "purpose"),
        "by_model": _group(window, "model"),
        "daily": [
            {"day": day, **_sum(daily_buckets[day])}
            for day in sorted(daily_buckets, reverse=True)
        ],
    }

    limit = max(0, int(budget or 0))
    if limit:
        used = today_stats["total_tokens"]
        result["budget"] = {
            "limit": limit,
            "used": used,
            "ratio": round(min(1.0, used / limit), 4),
            "remaining": max(0, limit - used),
        }
    return result


# ---------------------------------------------------------------- 落盘


def _path(plugin) -> str:
    from .config import USAGE_LOG_FILE

    return USAGE_LOG_FILE


def record(plugin, *, purpose: str, model: str = "", input_other: int = 0,
           input_cached: int = 0, output: int = 0, media_cached: bool = False) -> None:
    """追加一条用量记录。任何异常都吞掉——账本不能影响业务。"""
    entry = make_entry(
        purpose=purpose,
        model=model,
        input_other=input_other,
        input_cached=input_cached,
        output=output,
        media_cached=media_cached,
    )
    try:
        path = _path(plugin)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # 盘满 / 只读 / 被占用都无所谓，业务继续
        pass


def load(plugin, *, days: int = KEEP_DAYS) -> list[dict]:
    """读出账本并按天裁剪。文件不存在返回空列表。"""
    try:
        path = _path(plugin)
        if not os.path.exists(path):
            return []
        cutoff = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d")
        rows: list[dict] = []
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 半行（写到一半断电）直接跳过
                if isinstance(item, dict) and str(item.get("day", "")) >= cutoff:
                    rows.append(item)
        return rows
    except Exception:
        return []


def collect(plugin, *, days: int = 1, budget: int = 0) -> dict:
    """给路由用：读 + 聚合。永远返回结构，不抛。"""
    rows = load(plugin)
    return summarize(rows, days=days, budget=budget)
