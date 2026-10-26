"""评论发出后的可见性复核。

发评论接口返回 ``code=0`` 只说明服务端收下了请求，不代表这条评论对别人可见：
可能被折叠、被风控吞掉、或者进了阿瓦隆审核。这里在发出后按发评接口返回的
``rpid`` 定点回查，把「以为发出去了」变成「确认可见 / 确认不可见」。

三条硬规则：

1. **定点，不翻首页**。用 ``x/v2/reply/wbi/main`` 的 ``seek_rpid`` 直接定位这条评论，
   不再赌它还在第一页 20 条里 —— 热门视频 90 秒就能把新评论顶出首页。
2. **两个时点**。90 秒只能确认「已经可见」，不能判定「被屏蔽」：阿瓦隆 AI 审核实测
   平均 7~8 分钟。查不到先记 ``pending``，到确认时点（默认 10 分钟后）再判。
3. **双视角**。匿名（不带登录 Cookie）查不到、带 Cookie 查得到，才是「仅自己可见」。
   单视角分不清「被删」和「被屏蔽」。

**只读**：只发 GET，不做任何写操作。复核失败也只记日志、不改账本。

已知限制（写在这里，免得以后当成缺陷）：

- 90 秒 + 10 分钟是跨两个 ``asyncio.sleep`` 的后台任务，**进程重启会丢**。
- ``attr`` 的位图（17/21/22 位 = 仅自己可见）来自第三方逆向实测，官方文档没有；
  所以原始值一律原样落盘，B站 改值后还能回溯。
- «审核中» 没有独立字段，靠「匿名不可见 + 登录可见」推理，会和 ShadowBan 混在一起。
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from astrbot.api import logger

from .config import VERIFY_LOG_FILE

WBI_MAIN_URL = "https://api.bilibili.com/x/v2/reply/wbi/main"
REPLY_LIST_URL = "https://api.bilibili.com/x/v2/reply"
REPLY_REPLY_URL = "https://api.bilibili.com/x/v2/reply/reply"

VERIFY_DELAY_SECONDS = 90
"""普通评论的乐观确认延迟：只确认「可见」，查不到不算失败。"""

VERIFY_AT_DELAY_SECONDS = 30
"""带 @ 的评论更怕「以为发出去了」，更早确认一次。"""

VERIFY_CONFIRM_DELAY_SECONDS = 600
"""判定「被吞」的延迟。阿瓦隆审核约 7~8 分钟，太早判定会误报。"""

VERIFY_LOG_CAP = 200

VERIFY_PAGE_FALLBACK_MAX = 3
"""seek_rpid 未命中时最多往前翻几页（含第一页）。"""

VERIFY_CONCURRENCY = 3
"""同时在途的复核任务上限，控制风控面。"""

VERIFY_OID_MIN_INTERVAL = 5.0
"""同一个评论区两次复核的最小间隔（秒）。"""

CODE_DELETED = 12022
"""``reply/reply`` 对已被删除（或仅自己可见）的根评论返回的 code。"""

WEB_LOCATION = 1315875

STATE_VISIBLE = "visible"
"""匿名视角可见，state=0。"""

STATE_SELF_ONLY = "self_only"
"""仅自己可见：匿名查不到 + 登录查得到，或 state=17。"""

STATE_FOLDED = "folded"
"""被折叠：``folder.is_folded == true``。"""

STATE_INVISIBLE = "invisible"
"""``invisible == true``，前端拿到数据但不渲染。"""

STATE_DELETED = "deleted"
"""两个视角都查不到，且存在性探测明确返回 12022。"""

STATE_PENDING = "pending"
"""90 秒时点没查不到，等确认时点，**不是失败**。"""

STATE_UNVERIFIED = "unverified"
"""接口层失败或无法判断（风控 / 结构异常 / 存在性探测说不清）。"""

_SELF_ONLY_ATTR_BITS = (17, 21, 22)

_inflight = 0
_last_oid_check: dict[str, float] = {}


# ── 配置读取（都从 plugin.config 取，热生效） ──


def _config_int(plugin, key, default):
    try:
        return max(0, int(plugin.config.get(key, default)))
    except (TypeError, ValueError, AttributeError):
        return default


def _config_bool(plugin, key, default):
    try:
        value = plugin.config.get(key, default)
    except AttributeError:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def verify_enabled(plugin) -> bool:
    return _config_bool(plugin, "COMMENT_VERIFY_ENABLED", True)


# ── 视角 / 请求 ──


def build_view_headers(plugin, anonymous: bool) -> dict:
    """匿名视角只保留设备标识（BUVID3/BUVID4），不带任何登录态。"""
    headers = dict(plugin._headers())
    if not anonymous:
        return headers
    keep = {}
    for config_key, cookie_key in (("BUVID3", "buvid3"), ("BUVID4", "buvid4")):
        value = plugin.config.get(config_key, "")
        if value:
            keep[cookie_key] = value
    if keep:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in keep.items())
    else:
        headers.pop("Cookie", None)
    return headers


def _page_params(oid, rpid, offset, type_id):
    params = {
        "oid": oid,
        "type": type_id,
        "mode": 2,  # 2=仅按时间，绝不能用默认的 3（热度），否则新评论不在首页
        "pagination_str": json.dumps({"offset": offset}, separators=(",", ":")),
        "web_location": WEB_LOCATION,
    }
    if rpid is not None:
        params["seek_rpid"] = str(rpid)
    return params


async def _wbi_payload(plugin, params, anonymous):
    """签名后 GET；返回 (payload|None, error)。网络与风控都收敛成 error 字符串。"""
    try:
        signed = await plugin.sign_wbi_params(dict(params))
    except Exception as exc:  # 签名失败也照样发，服务端会返回 -403，由调用方记 unverified
        logger.debug(f"[BiliBot] 复核签名异常：{exc}")
        signed = dict(params)
    try:
        payload, _resp = await plugin._http_get(
            WBI_MAIN_URL,
            headers=build_view_headers(plugin, anonymous),
            params=signed,
            retries=1,
        )
    except Exception as exc:
        return None, f"http:{type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, "payload"
    code = payload.get("code", 0)
    if code != 0:
        return None, f"code:{code}"
    return payload, ""


async def fetch_seek(plugin, oid, rpid, *, anonymous, offset="", type_id=1):
    params = _page_params(oid, rpid, offset, type_id)
    return await _wbi_payload(plugin, params, anonymous)


def _next_offset(payload) -> str:
    data = (payload or {}).get("data")
    if not isinstance(data, dict):
        return ""
    cursor = data.get("cursor")
    if not isinstance(cursor, dict):
        return ""
    reply = cursor.get("pagination_reply")
    if not isinstance(reply, dict):
        return ""
    return str(reply.get("next_offset") or "")


async def fetch_sub_replies(plugin, oid, root, *, anonymous, max_pages: int = 2, type_id=1):
    """楼中楼查询：返回 (item|None, code)。用于二级回复与存在性探测。"""
    code = None
    for page in range(1, max(1, min(5, int(max_pages))) + 1):
        params = {
            "oid": oid,
            "type": type_id,
            "root": root,
            "pn": page,
            "ps": 20,
        }
        try:
            payload, _resp = await plugin._http_get(
                REPLY_REPLY_URL,
                headers=build_view_headers(plugin, anonymous),
                params=params,
                retries=1,
            )
        except Exception as exc:
            return None, f"http:{type(exc).__name__}"
        if not isinstance(payload, dict):
            return None, "payload"
        code = payload.get("code", 0)
        if code != 0:
            return None, code
        data = payload.get("data")
        replies = data.get("replies") if isinstance(data, dict) else None
        item, _bucket = _scan_list(replies, str(root))
        if item is not None:
            return item, code
    return None, code


async def probe_exists(plugin, oid, root, *, anonymous) -> str:
    """用 ``reply/reply`` 探测根评论还在不在：exists / gone / unknown。"""
    _item, code = await fetch_sub_replies(plugin, oid, root, anonymous=anonymous, max_pages=1)
    if code == CODE_DELETED:
        return "gone"
    if code == 0:
        return "exists"
    return "unknown"


# ── 解析与判定 ──


def _scan_list(items, target):
    if not isinstance(items, list):
        return None, ""
    for item in items:
        if isinstance(item, dict) and str(item.get("rpid")) == target:
            return item, ""
    return None, ""


def find_reply(payload, rpid):
    """在 replies / top / top_replies / hots 里找 rpid。置顶与热评不在 replies 里，必须一起扫。"""
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None, ""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, ""
    target = str(rpid)
    for bucket in ("replies", "top_replies", "hots"):
        item, _ = _scan_list(data.get(bucket), target)
        if item is not None:
            return item, bucket
    top = data.get("top")
    if isinstance(top, dict):
        for slot, item in top.items():
            if isinstance(item, dict) and str(item.get("rpid")) == target:
                return item, f"top.{slot}"
    return None, ""


def attr_hits_self_only(attr) -> bool:
    try:
        value = int(attr or 0)
    except (TypeError, ValueError):
        return False
    return any(value & (1 << bit) for bit in _SELF_ONLY_ATTR_BITS)


def classify_item(item) -> str:
    if not isinstance(item, dict):
        return STATE_UNVERIFIED
    folder = item.get("folder")
    if isinstance(folder, dict) and folder.get("is_folded"):
        return STATE_FOLDED
    if item.get("invisible"):
        return STATE_INVISIBLE
    try:
        state = int(item.get("state") or 0)
    except (TypeError, ValueError):
        return STATE_UNVERIFIED
    if state == 0:
        return STATE_VISIBLE
    if state in (11, 17, 18):  # 17 有文档；11/18 来自第三方实测，只当信号
        return STATE_SELF_ONLY
    if attr_hits_self_only(item.get("attr")):
        return STATE_SELF_ONLY
    return STATE_UNVERIFIED


def _fill_raw(result, item):
    result["raw_state"] = item.get("state")
    result["raw_attr"] = item.get("attr")
    result["raw_invisible"] = item.get("invisible")


async def scan_pages(plugin, oid, rpid, *, anonymous, payload, type_id=1):
    """seek_rpid 没命中时按 cursor 往前翻，命中即返回。"""
    limit = _config_int(plugin, "COMMENT_VERIFY_PAGE_FALLBACK_MAX", VERIFY_PAGE_FALLBACK_MAX)
    offset = _next_offset(payload)
    for _ in range(max(0, min(limit, 5) - 1)):
        if not offset:
            break
        page, err = await fetch_seek(plugin, oid, rpid, anonymous=anonymous, offset=offset, type_id=type_id)
        if err:
            break
        item, bucket = find_reply(page, rpid)
        if item is not None:
            return item, bucket
        offset = _next_offset(page)
    return None, ""


async def check_visibility(plugin, oid, rpid, *, kind="comment", phase="optimistic") -> dict:
    """跑一次可见性判定。``phase=optimistic`` 时查不到只记 pending，不下结论。"""
    target = str(rpid)
    anonymous = _config_bool(plugin, "COMMENT_VERIFY_ANONYMOUS", True)
    result = {
        "state": STATE_UNVERIFIED,
        "query_path": "wbi_seek",
        "view": "",
        "raw_state": None,
        "raw_attr": None,
        "raw_invisible": None,
        "raw_code": None,
        "error": "",
    }

    payload, err = await fetch_seek(plugin, oid, target, anonymous=anonymous)
    if err:
        result["error"] = err
        return result

    item, bucket = find_reply(payload, target)
    if item is None and phase != "optimistic":
        item, bucket = await scan_pages(plugin, oid, target, anonymous=anonymous, payload=payload)
        if item is not None:
            bucket = bucket or "wbi_pages"
    if item is not None:
        result["view"] = "anon" if anonymous else "auth"
        result["query_path"] = "wbi:" + (bucket or "seek")
        _fill_raw(result, item)
        result["state"] = classify_item(item)
        return result

    if phase == "optimistic":
        result["state"] = STATE_PENDING
        return result

    # 匿名不可见：换登录视角再查，差异即「仅自己可见」。
    # 关掉匿名视角时只剩单视角，分不清「被删」和「被屏蔽」，只做存在性探测。
    if anonymous:
        auth_payload, auth_err = await fetch_seek(plugin, oid, target, anonymous=False)
        if auth_err:
            result["error"] = auth_err
        else:
            auth_item, _bucket = find_reply(auth_payload, target)
            if auth_item is None:
                auth_item, _bucket = await scan_pages(
                    plugin, oid, target, anonymous=False, payload=auth_payload
                )
            if auth_item is not None:
                result["view"] = "both"
                _fill_raw(result, auth_item)
                state = classify_item(auth_item)
                result["state"] = (
                    state
                    if state in (STATE_FOLDED, STATE_INVISIBLE, STATE_SELF_ONLY)
                    else STATE_SELF_ONLY
                )
                return result

    # 两个视角都没有（或只开了单视角）：用楼中楼接口探测根评论是否还存在
    if kind == "reply":
        probe_item, probe_code = await fetch_sub_replies(plugin, oid, target, anonymous=True)
        result["raw_code"] = probe_code
        if probe_item is not None:
            result["state"] = STATE_SELF_ONLY
            return result
        if probe_code != CODE_DELETED:
            return result  # 仍是 unverified
        exists = await probe_exists(plugin, oid, target, anonymous=False)
        result["state"] = STATE_DELETED if exists == "gone" else STATE_UNVERIFIED
        return result

    exists = await probe_exists(plugin, oid, target, anonymous=False)
    result["raw_code"] = CODE_DELETED if exists == "gone" else None
    result["state"] = STATE_DELETED if exists == "gone" else STATE_UNVERIFIED
    return result

# ── 记录 ──


def _entry(oid, rpid, kind, has_at, phase, result, elapsed):
    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "oid": oid,
        "rpid": rpid,
        "kind": kind,
        "has_at": has_at,
        "phase": phase,
        "query_path": result.get("query_path", ""),
        "view": result.get("view", ""),
        "raw_state": result.get("raw_state"),
        "raw_attr": result.get("raw_attr"),
        "raw_invisible": result.get("raw_invisible"),
        "raw_code": result.get("raw_code"),
        "state": result.get("state", STATE_UNVERIFIED),
        "error": result.get("error", ""),
        "elapsed": round(elapsed, 1),
    }


def _record(plugin, entry):
    try:
        plugin._append_json_list(VERIFY_LOG_FILE, entry, cap=VERIFY_LOG_CAP)
    except Exception as exc:
        logger.debug(f"[BiliBot] 写复核日志失败：{exc}")


def _report(entry):
    state = entry["state"]
    if state == STATE_VISIBLE:
        logger.info(f"[BiliBot] 评论复核通过：rpid={entry['rpid']}（{entry['phase']}）")
    elif state == STATE_PENDING:
        logger.debug(f"[BiliBot] 评论复核待确认：rpid={entry['rpid']}，10 分钟后再判")
    else:
        logger.warning(
            f"[BiliBot] 评论复核未确认可见：oid={entry['oid']} rpid={entry['rpid']} "
            f"→ {state}（{entry['phase']}，{entry.get('error') or '—'}）"
        )


async def _throttle_oid(oid):
    """同一评论区两次复核至少隔几秒，别把它当压力测试。"""
    key = str(oid)
    now = time.monotonic()
    last = _last_oid_check.get(key)
    if last is not None and now - last < VERIFY_OID_MIN_INTERVAL:
        await asyncio.sleep(VERIFY_OID_MIN_INTERVAL - (now - last))
    _last_oid_check[key] = time.monotonic()
    if len(_last_oid_check) > 200:
        for stale in sorted(_last_oid_check, key=_last_oid_check.get)[:100]:
            _last_oid_check.pop(stale, None)


# ── 调度 ──


async def verify_later(plugin, oid, rpid, *, delay=None, kind="comment", has_at=False, confirm_delay=None):
    """等 ``delay`` 秒后复核一次；仍是 pending 就再等到确认时点。返回最终状态。"""
    if delay is None:
        delay = _config_int(plugin, "COMMENT_VERIFY_DELAY_SECONDS", VERIFY_DELAY_SECONDS)
    if has_at:
        delay = min(delay, _config_int(plugin, "COMMENT_VERIFY_AT_DELAY_SECONDS", VERIFY_AT_DELAY_SECONDS))
    if confirm_delay is None:
        confirm_delay = _config_int(
            plugin, "COMMENT_VERIFY_CONFIRM_DELAY_SECONDS", VERIFY_CONFIRM_DELAY_SECONDS
        )
    started = time.monotonic()
    try:
        await asyncio.sleep(max(0, delay))
        await _throttle_oid(oid)
        first = await check_visibility(plugin, oid, rpid, kind=kind, phase="optimistic")
        entry = _entry(oid, rpid, kind, has_at, "optimistic", first, time.monotonic() - started)
        _record(plugin, entry)
        _report(entry)
        if first["state"] != STATE_PENDING:
            return first["state"]

        await asyncio.sleep(max(0, confirm_delay))
        await _throttle_oid(oid)
        second = await check_visibility(plugin, oid, rpid, kind=kind, phase="confirm")
        entry = _entry(oid, rpid, kind, has_at, "confirm", second, time.monotonic() - started)
        _record(plugin, entry)
        _report(entry)
        return second["state"]
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # 复核是旁路，绝不能让异常逃到调用方
        logger.debug(f"[BiliBot] 复核任务异常（oid={oid} rpid={rpid}）：{exc}")
        return STATE_UNVERIFIED


def schedule_verify(plugin, oid, rpid, *, delay=None, kind="comment", has_at=False) -> bool:
    """排一次后台复核。没有 rpid / 没有事件循环 / 并发满时安静跳过。"""
    global _inflight
    if not rpid or not verify_enabled(plugin):
        return False
    try:
        rpid_int = int(rpid)
    except (TypeError, ValueError):
        return False
    if rpid_int <= 0:
        return False
    limit = _config_int(plugin, "COMMENT_VERIFY_MAX_CONCURRENCY", VERIFY_CONCURRENCY)
    if limit and _inflight >= limit:
        logger.debug(f"[BiliBot] 复核并发已满（{_inflight}/{limit}），本轮跳过 rpid={rpid_int}")
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("[BiliBot] 当前没有事件循环，跳过评论复核")
        return False
    _inflight += 1
    task = loop.create_task(
        verify_later(plugin, oid, rpid_int, delay=delay, kind=kind, has_at=has_at)
    )
    task.add_done_callback(_release_slot)
    return True


def _release_slot(_task):
    global _inflight
    _inflight = max(0, _inflight - 1)


def parse_reply_state(payload, rpid) -> str:
    """兼容旧调用：从任意列表型响应里判断某条评论的状态（找不到记 pending）。"""
    item, _bucket = find_reply(payload, rpid)
    if item is not None:
        return classify_item(item)
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return STATE_UNVERIFIED
    return STATE_PENDING
