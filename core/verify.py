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

VERIFY_PAGE_FALLBACK_MAX = 2
"""seek_rpid 未命中时最多翻到第几页（含第一页）。默认 2，避免异常路径上反复打请求。"""

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


def _page_params(oid, rpid, offset, type_id, *, seek=True):
    params = {
        "oid": oid,
        "type": type_id,
        "mode": 2,  # 2=仅按时间，绝不能用默认的 3（热度），否则新评论不在首页
        "pagination_str": json.dumps({"offset": offset}, separators=(",", ":")),
        "web_location": WEB_LOCATION,
    }
    # seek_rpid 的语义是「定位到这条评论所在分页」，翻页时必须去掉，
    # 否则服务端每次都重新定位回同一页，pagination offset 形同虚设。
    if seek and rpid is not None:
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
    if not isinstance(payload.get("data"), dict):
        # code=0 但结构不对：不能说成「查了但没查到」，否则下一步的登录视角
        # 会把它判成「仅自己可见」（同一个误判的另一个入口）。
        return None, "payload:data"
    return payload, ""


async def fetch_seek(plugin, oid, rpid, *, anonymous, offset="", type_id=1, seek=True):
    params = _page_params(oid, rpid, offset, type_id, seek=seek)
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


async def fetch_sub_replies(plugin, oid, root, *, anonymous, target=None, max_pages: int = 2, type_id=1):
    """楼中楼查询：在 root 的回复列表里找 target，返回 (item|None, code)。

    ``target`` 不给时按 root 自身找——那只是存在性探测，靠 code 判断，
    不能用它来找「我发的那条回复」（回复的 root 是父评论，不是它自己）。
    """
    want = str(target or root)
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
        item, _bucket = _scan_list(replies, want)
        if item is not None:
            return item, code
    return None, code


async def probe_exists(plugin, oid, root, *, anonymous, type_id=1) -> str:
    """用 ``reply/reply`` 探测评论还在不在：exists / gone / unknown。"""
    _item, code = await fetch_sub_replies(
        plugin, oid, root, anonymous=anonymous, max_pages=1, type_id=type_id
    )
    if code == CODE_DELETED:
        return "gone"
    if code == 0:
        return "exists"
    return "unknown"


# ── 解析与判定 ──


def _walk_replies(items, seen, depth=0):
    """按原始顺序深度优先展开评论树：父在前、子按列表顺序，已访问过的节点跳过。

    楼中楼（二级回复）不在顶层列表里，而是挂在每条评论的 ``replies`` 下；它可能为空、
    可能多层嵌套（``replies`` 里还有 ``replies``），同一条也可能被置顶/热评/首页列表
    重复引用，所以按对象 id 去重，避免重复扫描和自引用打转。
    """
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        key = id(item)
        if key in seen:
            continue
        seen.add(key)
        yield item, depth
        yield from _walk_replies(item.get("replies"), seen, depth + 1)


def _scan_list(items, target):
    """在一条回复列表（连同其楼中楼）里找 rpid，返回 (item|None, "")。"""
    target = str(target)
    for item, _depth in _walk_replies(items, set()):
        if str(item.get("rpid")) == target:
            return item, ""
    return None, ""


def find_reply(payload, rpid):
    """在 replies / top / top_replies / hots 及其楼中楼里找 rpid。

    置顶与热评不在 replies 里，必须一起扫；二级回复挂在各评论的 ``replies`` 下，
    不往子列表里递归就永远命中不了正常可见的楼中楼，只能掉到兜底分支去判。
    """
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None, ""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, ""
    target = str(rpid)
    seen = set()
    for bucket in ("replies", "top_replies", "hots"):
        for item, depth in _walk_replies(data.get(bucket), seen):
            if str(item.get("rpid")) == target:
                return item, bucket if depth == 0 else f"{bucket}.sub"
    top = data.get("top")
    if isinstance(top, dict):
        for slot, value in top.items():
            for item, depth in _walk_replies([value], seen):
                if str(item.get("rpid")) == target:
                    return item, f"top.{slot}" if depth == 0 else f"top.{slot}.sub"
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
    """seek_rpid 没命中时按 cursor 往前翻，命中即返回。翻页不带 seek_rpid。

    返回 ``(item, bucket, error)``。翻页请求失败时必须把 error 带回去：
    把「翻页被风控吞了」当成「查不到」，下一步的登录视角就会判成「仅自己可见」。
    """
    limit = _config_int(plugin, "COMMENT_VERIFY_PAGE_FALLBACK_MAX", VERIFY_PAGE_FALLBACK_MAX)
    offset = _next_offset(payload)
    for _ in range(max(0, min(limit, 5) - 1)):
        if not offset:
            break
        page, err = await fetch_seek(
            plugin, oid, rpid, anonymous=anonymous, offset=offset, type_id=type_id, seek=False
        )
        if err:
            return None, "", err
        item, bucket = find_reply(page, rpid)
        if item is not None:
            return item, bucket, ""
        offset = _next_offset(page)
    return None, "", ""


async def check_visibility(
    plugin, oid, rpid, *, kind="comment", phase="optimistic", type_id=1, root_rpid=0
) -> dict:
    """跑一次可见性判定。``phase=optimistic`` 时查不到只记 pending，不下结论。

    ``type_id`` 是评论区类型（视频=1、动态=17），必须与发送时一致；
    ``root_rpid`` 只对二级回复有意义：它指向被回复的父评论，用来在楼中楼里找自己。
    """
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

    payload, err = await fetch_seek(plugin, oid, target, anonymous=anonymous, type_id=type_id)
    if err:
        result["error"] = err
        return result

    item, bucket = find_reply(payload, target)
    if item is None and phase != "optimistic":
        item, bucket, page_err = await scan_pages(
            plugin, oid, target, anonymous=anonymous, payload=payload, type_id=type_id
        )
        if item is not None:
            bucket = bucket or "wbi_pages"
        elif page_err:
            # 匿名视角翻页失败：「匿名看不到」不成立，不能再换登录视角反推仅自己可见。
            result["error"] = page_err
            return result
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
        auth_payload, auth_err = await fetch_seek(
            plugin, oid, target, anonymous=False, type_id=type_id
        )
        if auth_err:
            result["error"] = auth_err
        else:
            auth_item, _bucket = find_reply(auth_payload, target)
            if auth_item is None:
                auth_item, _bucket, auth_page_err = await scan_pages(
                    plugin, oid, target, anonymous=False, payload=auth_payload, type_id=type_id
                )
                if auth_page_err:
                    # 登录视角翻页失败只影响「登录也看不到」这个结论；后面还有楼中楼接口
                    # 与存在性探测兜底，所以不在这里返回，只把原因记下来。
                    result["error"] = auth_page_err
            if auth_item is not None:
                result["view"] = "auth"
                _fill_raw(result, auth_item)
                state = classify_item(auth_item)
                result["state"] = (
                    state
                    if state in (STATE_FOLDED, STATE_INVISIBLE, STATE_SELF_ONLY)
                    else STATE_SELF_ONLY
                )
                return result

    # 两个视角都没有（或只开了单视角）：改到楼中楼里找。
    # 二级回复的 root 是「被回复的父评论」；拿自身 rpid 当 root 永远找不到自己。
    if kind == "reply":
        root = str(root_rpid or target)
        # 段一：匿名视角。能查到就说明它对所有人可见——原先这里一律判「仅自己可见」，
        # 语义是反的：匿名查得到恰恰是「公开可见」的证据。
        # 这里固定走两段、不受 COMMENT_VERIFY_ANONYMOUS 影响：单视角分不清「公开可见」和「仅自己可见」。
        anon_item, anon_code = await fetch_sub_replies(
            plugin, oid, root, anonymous=True, target=target, type_id=type_id
        )
        result["raw_code"] = anon_code
        if anon_item is not None:
            result["view"] = "anon"
            result["query_path"] = "sub_reply:anon"
            _fill_raw(result, anon_item)
            state = classify_item(anon_item)
            # attr/state 位图只是信号；匿名接口确实返回了它，以「能看到」为准。
            result["state"] = (
                STATE_VISIBLE if state in (STATE_SELF_ONLY, STATE_UNVERIFIED) else state
            )
            return result
        if anon_code not in (0, CODE_DELETED):
            # 匿名视角查询本身失败（风控 / 网络 / 结构异常）：这不算「查不到」，
            # 再拿登录视角反推「仅自己可见」就是同一个误判的另一个入口。
            result["error"] = f"sub_reply:{anon_code}"
            return result

        # 段二：匿名看不到再换登录视角。登录能看到 = 仅自己可见。
        auth_item, auth_code = await fetch_sub_replies(
            plugin, oid, root, anonymous=False, target=target, type_id=type_id
        )
        if auth_code:
            result["raw_code"] = auth_code
        if auth_item is not None:
            result["view"] = "auth"
            result["query_path"] = "sub_reply:auth"
            _fill_raw(result, auth_item)
            state = classify_item(auth_item)
            result["state"] = (
                state if state in (STATE_FOLDED, STATE_INVISIBLE) else STATE_SELF_ONLY
            )
            return result

        # 两段都查不到：登录视角的 reply/reply 对已删根评论才返回 12022，
        # 匿名视角返回 12022 也可能是「根评论仅自己可见」，所以只认登录视角的 code。
        if auth_code == CODE_DELETED:
            result["state"] = STATE_DELETED
        elif auth_code not in (0, None):
            result["error"] = f"sub_reply:{auth_code}"
        return result  # 说不清的仍旧留 unverified

    exists = await probe_exists(plugin, oid, target, anonymous=False, type_id=type_id)
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


_STATE_HINTS = {
    STATE_SELF_ONLY: "仅自己可见：匿名查不到、登录查得到",
    STATE_FOLDED: "被折叠",
    STATE_INVISIBLE: "接口返回了但前端不渲染",
    STATE_DELETED: "已不可见：根评论没了",
    STATE_UNVERIFIED: "没查成（风控 / 网络 / 结构异常或说不清），不据此下结论",
}


def _report(entry):
    state = entry["state"]
    if state == STATE_VISIBLE:
        logger.info(f"[BiliBot] 评论复核通过：rpid={entry['rpid']}（{entry['phase']}）")
    elif state == STATE_PENDING:
        logger.debug(f"[BiliBot] 评论复核待确认：rpid={entry['rpid']}，10 分钟后再判")
    else:
        # self_only 是「有结论」，unverified 是「没查成」，别用同一句话糊过去
        logger.warning(
            f"[BiliBot] 评论复核未确认可见：oid={entry['oid']} rpid={entry['rpid']} "
            f"→ {state}（{_STATE_HINTS.get(state) or '未知状态'}；{entry['phase']}，"
            f"{entry.get('error') or '—'}）"
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


async def verify_later(
    plugin, oid, rpid, *, delay=None, kind="comment", has_at=False, confirm_delay=None,
    type_id=1, root_rpid=0,
):
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
        first = await check_visibility(
            plugin, oid, rpid, kind=kind, phase="optimistic", type_id=type_id, root_rpid=root_rpid
        )
        entry = _entry(oid, rpid, kind, has_at, "optimistic", first, time.monotonic() - started)
        _record(plugin, entry)
        _report(entry)
        if first["state"] != STATE_PENDING:
            return first["state"]

        await asyncio.sleep(max(0, confirm_delay))
        await _throttle_oid(oid)
        second = await check_visibility(
            plugin, oid, rpid, kind=kind, phase="confirm", type_id=type_id, root_rpid=root_rpid
        )
        entry = _entry(oid, rpid, kind, has_at, "confirm", second, time.monotonic() - started)
        _record(plugin, entry)
        _report(entry)
        return second["state"]
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # 复核是旁路，绝不能让异常逃到调用方
        logger.debug(f"[BiliBot] 复核任务异常（oid={oid} rpid={rpid}）：{exc}")
        return STATE_UNVERIFIED


def schedule_verify(
    plugin, oid, rpid, *, delay=None, kind="comment", has_at=False, type_id=1, root_rpid=0
) -> bool:
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
        verify_later(
            plugin, oid, rpid_int, delay=delay, kind=kind, has_at=has_at,
            type_id=type_id, root_rpid=root_rpid,
        )
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
