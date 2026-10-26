"""watch_log 的长期存储：主文件留最近窗口，溢出的按月归档。

写入侧不再「只留 200 条」：

- ``watch_log.json`` 保留最近 ``WATCH_LOG_ACTIVE_CAP``（默认 500）条，供高频读取直接消费；
- 溢出的条目按月写进 ``data/watch_log_archive/YYYY-MM.json``（结构同样是 list，条目原样保留）；
- 需要长期数据的地方（卡片墙、自检计数）用 ``load_watch_entries()`` 合并归档 + 主文件。

为什么不是 SQLite：见进度文档 T44 的实测对比 —— 月归档把单次追加压到 9~35 ms，
SQLite 的体积约 1.8 倍且要改全部消费点。SQLite 留作预选项。

归档失败时**不裁剪主文件**：宁可文件大一点，也不丢记录。
"""

from __future__ import annotations

import os

from astrbot.api import logger

from .config import DATA_DIR, WATCH_LOG_FILE

WATCH_LOG_ACTIVE_CAP = 500
"""主文件保留的条数；超出部分按月进归档。"""

ARCHIVE_DIRNAME = "watch_log_archive"


def archive_dir() -> str:
    return os.path.join(DATA_DIR, ARCHIVE_DIRNAME)


def entry_month(entry) -> str:
    """按条目自己的 time 决定归档月份；时间格式异常时归到 unknown。"""
    text = str((entry or {}).get("time") or "")
    month = text[:7]
    if len(month) == 7 and month[4] == "-" and month[:4].isdigit():
        return month
    return "unknown"


def _archive_entries(plugin, entries):
    grouped = {}
    for item in entries:
        if isinstance(item, dict):
            grouped.setdefault(entry_month(item), []).append(item)
    if not grouped:
        return
    directory = archive_dir()
    os.makedirs(directory, exist_ok=True)
    for month, items in grouped.items():
        path = os.path.join(directory, f"{month}.json")
        existing = plugin._load_json(path, [])
        if not isinstance(existing, list):
            existing = []
        existing.extend(items)
        plugin._save_json(path, existing)


def append_watch_entry(plugin, entry, *, cap=None):
    """追加一条观看记录，并把溢出部分按月归档。返回主文件当前内容。"""
    limit = max(1, int(cap or WATCH_LOG_ACTIVE_CAP))
    rows = plugin._load_json(WATCH_LOG_FILE, [])
    if not isinstance(rows, list):
        rows = []
    rows.append(entry)
    overflow = rows[:-limit] if len(rows) > limit else []
    active = rows[-limit:]
    if overflow:
        try:
            _archive_entries(plugin, overflow)
        except Exception as exc:
            logger.warning(f"[BiliBot] 归档 watch_log 失败，暂不裁剪主文件：{exc}")
            active = rows
    plugin._save_json(WATCH_LOG_FILE, active)
    return active


def load_watch_entries(plugin, *, months=None):
    """合并归档与主文件，按 time 升序返回；同一 (time, bvid) 只留最新一份。"""
    rows = []
    directory = archive_dir()
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            if months and name[:-5] not in months:
                continue
            data = plugin._load_json(os.path.join(directory, name), [])
            if isinstance(data, list):
                rows.extend(item for item in data if isinstance(item, dict))
    active = plugin._load_json(WATCH_LOG_FILE, [])
    if isinstance(active, list):
        rows.extend(item for item in active if isinstance(item, dict))

    buckets = {}
    for item in rows:
        key = (str(item.get("time") or ""), str(item.get("bvid") or ""))
        buckets[key] = item  # 主文件排在最后，覆盖归档里的同名旧条目
    return [buckets[key] for key in sorted(buckets)]


def update_watch_entry(plugin, bvid, patch):
    """按 bvid 更新最近一条记录（先主文件、再按月归档从新到旧）。"""
    target = str(bvid or "").strip()
    if not target or not isinstance(patch, dict):
        return False

    active = plugin._load_json(WATCH_LOG_FILE, [])
    if isinstance(active, list):
        for item in reversed(active):
            if isinstance(item, dict) and str(item.get("bvid") or "") == target:
                item.update(patch)
                plugin._save_json(WATCH_LOG_FILE, active)
                return True

    directory = archive_dir()
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory), reverse=True):
            if not name.endswith(".json"):
                continue
            path = os.path.join(directory, name)
            data = plugin._load_json(path, [])
            if not isinstance(data, list):
                continue
            for item in reversed(data):
                if isinstance(item, dict) and str(item.get("bvid") or "") == target:
                    item.update(patch)
                    plugin._save_json(path, data)
                    return True
    return False


def watch_entry_count(plugin):
    """总条数（归档 + 主文件）；读不到返回 None，交给自检页显示「文件损坏」。"""
    try:
        return len(load_watch_entries(plugin))
    except Exception:
        return None
