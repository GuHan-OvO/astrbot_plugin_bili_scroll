"""评论发出后的复核。

发评论接口返回 ``code=0`` 只说明「服务端接受了请求」，不代表这条评论真的对别人可见：
可能被折叠、被风控吞掉、或者刚发出去就没了。这里在发出后延迟一段时间读回一次，
把「以为发出去了」变成「确认可见」。

**只读**：只用 GET 评论列表，不做任何写操作。
复核失败也只记日志、不改账本 —— 删不删是人的决定，不是它的。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger

from .config import VERIFY_LOG_FILE

VERIFY_DELAY_SECONDS = 90
"""延迟多久复核。太短可能还没刷进列表，太长就没有意义了。"""

VERIFY_LOG_CAP = 100
"""本地只留最近这些条复核记录。"""

REPLY_LIST_URL = "https://api.bilibili.com/x/v2/reply"

STATE_VISIBLE = "visible"
STATE_HIDDEN = "hidden"
STATE_MISSING = "missing"
STATE_ERROR = "error"


def parse_reply_state(payload, rpid) -> str:
    """从评论列表响应里判断某条评论的状态。

    返回：

    - ``visible`` 找到了且 state 正常（对别人可见）
    - ``hidden``  找到了但被折叠 / 审核中（state 非 0）
    - ``missing`` 前若干条里没有（被删、被折叠到后面，或评论太多被顶走）
    - ``error``   响应本身异常

    注意 ``missing`` **不等于被删**：热门视频里新评论很快会被顶出第一页，
    所以这一项只能当「没确认到」，不能当「失败」。
    """
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return STATE_ERROR
    data = payload.get("data")
    if not isinstance(data, dict):
        return STATE_ERROR
    replies = data.get("replies")
    if not isinstance(replies, list):
        return STATE_ERROR

    target = str(rpid)
    for item in replies:
        if not isinstance(item, dict):
            continue
        if str(item.get("rpid")) != target:
            continue
        try:
            state = int(item.get("state", 0) or 0)
        except (TypeError, ValueError):
            return STATE_HIDDEN
        return STATE_VISIBLE if state == 0 else STATE_HIDDEN
    return STATE_MISSING


async def check_comment(plugin, oid, rpid, *, page_size: int = 20) -> str:
    """读回一次评论列表并判断状态；网络异常也归到 ``error``。"""
    try:
        payload, _ = await plugin._http_get(
            REPLY_LIST_URL,
            params={
                "oid": oid,
                "type": 1,
                "sort": 0,  # 0=按时间倒序，刚发的排前面
                "pn": 1,
                "ps": max(1, min(20, int(page_size))),
            },
        )
    except Exception as exc:
        logger.debug(f"[BiliBot] 复核读回失败（oid={oid} rpid={rpid}）：{exc}")
        return STATE_ERROR
    return parse_reply_state(payload, rpid)


def _record(plugin, entry: dict) -> None:
    """把复核结果追加进本地日志；写不进去也不影响主流程。"""
    try:
        plugin._append_json_list(VERIFY_LOG_FILE, entry, cap=VERIFY_LOG_CAP)
    except Exception as exc:
        logger.debug(f"[BiliBot] 写复核日志失败：{exc}")


async def verify_later(plugin, oid, rpid, *, delay: float = VERIFY_DELAY_SECONDS) -> str:
    """等 ``delay`` 秒后复核一次并记账。返回最终状态，便于测试直接 await。"""
    try:
        await asyncio.sleep(max(0, delay))
    except asyncio.CancelledError:
        raise
    state = await check_comment(plugin, oid, rpid)

    from datetime import datetime

    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "oid": oid,
        "rpid": rpid,
        "state": state,
    }
    if state == STATE_VISIBLE:
        logger.info(f"[BiliBot] 评论复核通过：rpid={rpid}")
    else:
        logger.warning(f"[BiliBot] 评论复核未通过：oid={oid} rpid={rpid} → {state}")
    _record(plugin, entry)
    return state


def schedule_verify(plugin, oid, rpid, *, delay: float = VERIFY_DELAY_SECONDS) -> bool:
    """把复核排到后台。没有事件循环（如单测环境）时安静跳过。"""
    if not rpid:
        return False
    try:
        asyncio.get_running_loop().create_task(verify_later(plugin, oid, rpid, delay=delay))
        return True
    except RuntimeError:
        logger.debug("[BiliBot] 当前没有事件循环，跳过评论复核")
        return False
