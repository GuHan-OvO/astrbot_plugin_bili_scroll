"""自检：把「插件现在是不是真的能跑」变成一页能看的东西。

只读，不写任何文件、不发任何 B站 请求（Cookie 检查是单独的显式动作）。
所有密钥类配置只报告「有没有配 / 长度」，绝不回显值。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .config import DATA_DIR, PLUGIN_NAME, WATCH_LOG_FILE, VERIFY_LOG_FILE

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
"""插件根目录（`core/` 的上一级）。"""

# 必填配置：名字 → 人话说明
REQUIRED_CONFIG = {
    "SESSDATA": "B站 登录态（bili登录 扫码获取）",
    "BILI_JCT": "B站 CSRF（与 SESSDATA 一起给出）",
    "OWNER_BILI_NAME": "主人 B站 昵称，用于真实 @ 提及",
    "OWNER_MID": "主人 B站 UID，与昵称配对",
}

SECRET_KEYS = {"SESSDATA", "BILI_JCT"}

OPTIONAL_CONFIG = {
    "ENABLE_PROACTIVE": "主动看片总开关（默认关）",
    "OWNER_QQ_UMO": "QQ 推荐投递地址",
    "ANALYSIS_DEPTH": "看多细",
    "PC_BRIDGE_ENABLE": "借陪伴插件的人格与通道",
}


def _config_value(plugin, key: str) -> Any:
    try:
        return plugin.config.get(key, None)
    except Exception:
        return None


def _is_filled(value: Any) -> bool:
    return bool(str(value or "").strip())


def _read_metadata() -> dict:
    """读插件自己的 metadata.yaml；读不到就返回空（不让自检因为元数据挂掉）。"""
    path = PLUGIN_ROOT / "metadata.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml  # AstrBot 环境自带

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug(f"[BiliBot] 自检读 metadata 失败：{exc}")
        return {}


_VERSION_CACHE: str | None = None


def plugin_version() -> str:
    """插件版本：唯一真源是 ``metadata.yaml``，读不到返回空串。"""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        _VERSION_CACHE = str(_read_metadata().get("version") or "")
    return _VERSION_CACHE


def _json_list_len(path: str) -> int | None:
    """只读列表型 JSON 的长度；文件不存在返回 0，坏了返回 None。"""
    try:
        if not os.path.exists(path):
            return 0
        import json

        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        return len(data) if isinstance(data, list) else None
    except Exception:
        return None


def _module_info() -> dict:
    return {
        "plugin_name": PLUGIN_NAME,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "plugin_root": str(PLUGIN_ROOT),
        "data_dir": str(DATA_DIR),
    }


def _config_report(plugin) -> dict:
    required = []
    for key, hint in REQUIRED_CONFIG.items():
        value = _config_value(plugin, key)
        filled = _is_filled(value)
        item = {"key": key, "hint": hint, "ok": filled}
        # 密钥只报长度，不报值
        item["detail"] = f"已配置（{len(str(value))} 字符）" if filled else "未配置"
        required.append(item)

    optional = []
    for key, hint in OPTIONAL_CONFIG.items():
        value = _config_value(plugin, key)
        optional.append({"key": key, "hint": hint, "value": value if not isinstance(value, str) else (value[:40] or "（空）")})

    try:
        total = len(plugin.config.keys())
    except Exception:
        total = 0
    return {"total_keys": total, "required": required, "optional": optional}


_ANOMALY_STATES = ("self_only", "folded", "invisible", "deleted")
"""复核日志里真算「不对」的状态。``pending`` 是正常中间态、``unverified`` 是没查成，都不列。"""


def _verify_rows() -> list:
    """读复核日志；不存在或坏掉一律当空（自检不能因为日志坏了而挂）。"""
    try:
        if not os.path.exists(VERIFY_LOG_FILE):
            return []
        import json

        with open(VERIFY_LOG_FILE, encoding="utf-8") as fp:
            rows = json.load(fp)
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def _pick_verify_rows(states, limit: int = 5) -> list[dict]:
    """按状态挑最近几条，只报状态与 rpid，不报评论正文。"""
    picked = [
        {
            "time": row.get("time", ""),
            "rpid": row.get("rpid"),
            "state": row.get("state", ""),
            "phase": row.get("phase", ""),
        }
        for row in _verify_rows()
        if isinstance(row, dict) and row.get("state") in states
    ]
    return picked[-limit:]


def _recent_verify(limit: int = 5) -> list[dict]:
    """最近几条**确认不正常**的复核记录（仅自己可见 / 折叠 / 不可见 / 已删）。

    ``pending`` 是 90 秒那次的正常中间态（10 分钟确认后会再写一条），``unverified`` 是接口层
    没查成；把它们当成「异常」会让自检页常年挂着并不代表出问题的行。
    """
    return _pick_verify_rows(_ANOMALY_STATES, limit)


def _recent_unverified(limit: int = 5) -> list[dict]:
    """最近几条「没查成」的复核记录（风控 / 网络 / 结构异常 / 说不清）。"""
    return _pick_verify_rows(("unverified",), limit)


def _watch_total(plugin):
    """归档 + 主文件的总条数；没有插件实例时返回 None。"""
    if plugin is None:
        return None
    try:
        from .watch_log import watch_entry_count

        return watch_entry_count(plugin)
    except Exception:
        return None


def _data_report(plugin=None) -> dict:
    watch_count = _json_list_len(WATCH_LOG_FILE)
    verify_count = _json_list_len(VERIFY_LOG_FILE)
    db = Path(DATA_DIR) / "bilibot.sqlite3"
    return {
        "watch_log": {"path": WATCH_LOG_FILE, "count": watch_count, "total": _watch_total(plugin)},
        "verify_log": {"path": VERIFY_LOG_FILE, "count": verify_count},
        "verify_recent": _recent_verify(),
        "verify_unverified": _recent_unverified(),
        "database": {"path": str(db), "exists": db.is_file(),
                     "size": db.stat().st_size if db.is_file() else 0},
    }


def _pages_report() -> list[dict]:
    """列出插件自带的页面目录（AstrBot 会把这些暴露成插件页面）。"""
    root = PLUGIN_ROOT / "pages"
    out: list[dict] = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "index.html").is_file():
            out.append({"name": entry.name, "has_index": True})
    return out


def collect(plugin) -> dict:
    """汇总所有自检信息。任何一段失败都只记错误，不影响其它段。

    注意：这里的键名**不能叫 `data`**。后端响应用的是 `{"status": "ok", "data": <本函数返回值>}`
    这套信封，前端 `unwrap()` 会执行 `result?.data ?? result`。如果本函数返回的字典里也有
    一个 `data` 键，解包后拿到的就是那一段报告本身，`module` / `config` / `routes` 全部变成
    undefined —— 表现是四个区块一起「读取失败」且不报错（2026-10-25 实测踩到）。
    所以存储统计那段改用 `storage`。
    """
    meta = _read_metadata()
    result: dict = {"ok": True, "errors": []}

    for key, builder in (
        ("module", lambda: _module_info()),
        ("metadata", lambda: {
            "name": meta.get("name"),
            "display_name": meta.get("display_name"),
            "version": meta.get("version"),
            "repo": meta.get("repo", ""),
            "author": meta.get("author"),
        }),
        ("config", lambda: _config_report(plugin)),
        ("storage", lambda: _data_report(plugin)),
        ("pages", lambda: _pages_report()),
    ):
        try:
            result[key] = builder()
        except Exception as exc:  # 单段失败不拖垮整页
            result[key] = None
            result["errors"].append(f"{key}: {exc}")

    # 路由前缀直接来自模块常量，用来核对「注册到哪条路径」
    result["routes"] = {
        "prefix": f"/{PLUGIN_NAME}",
        "examples": [f"/{PLUGIN_NAME}/history", f"/{PLUGIN_NAME}/stats",
                     f"/{PLUGIN_NAME}/selftest"],
    }
    result["ok"] = not result["errors"]
    return result
