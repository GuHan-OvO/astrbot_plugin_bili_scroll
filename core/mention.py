"""评论区「真 @」的映射构造。

B站 的评论接口只有在请求体里带 ``at_name_to_mid``（``{"昵称": uid}`` 的 JSON 字符串）
时，才会把正文里的 ``@昵称`` 解析成真实提及 —— 这一点可以用读回来的
``content.members`` 是否有值来判断（纯文本 @ 时该数组为空）。

本模块只做纯逻辑：构造映射、规范化正文、昵称兜底解析。
不做网络请求，也不读全局配置，方便单测。

设计取舍：
- **主路径不搜索**：配置里同时有昵称和 UID 时直接拼映射，省一次请求、也不会解析错人。
- **解析不到就不 @**：宁可退化成纯文本，也不把评论 @ 到同名的陌生人身上。
"""

from __future__ import annotations

import re

from astrbot.api import logger

AT_NAME_MAX_LEN = 32
"""B站 昵称最长 32 字节，超过就不可能有效。"""

MID_MAX = 2**63 - 1
"""MID 的合理上界，用来挡住明显异常的配置值。"""

# 「@昵称」的右边界：只有后面跟空白、串尾或常见标点时才算一次提及。
# 不加这个判断，`@某用户` 会把 `@某用户A` 里的前半段吃掉，改出语义不同的正文。
_AT_BOUNDARY = r"(?=\s|$|[，。！？、；：,.!?;:）)\]】》」』\"'…—-])"


def build_mention_map(owner_name, owner_mid) -> dict[str, int]:
    """从配置构造 ``{昵称: uid}``；任一项无效就返回空字典。

    返回空字典时调用方应退化为「发纯文本评论」（不加该字段），
    而不是尝试猜一个 UID —— 猜错会把评论 @ 到无关的人。
    """
    name = str(owner_name or "").strip().lstrip("@").strip()
    if not name or len(name) > AT_NAME_MAX_LEN:
        return {}

    try:
        mid = int(str(owner_mid).strip())
    except (TypeError, ValueError):
        return {}

    if not 0 < mid <= MID_MAX:
        return {}
    return {name: mid}


def compose_comment(text, name) -> str:
    """把正文规范成 ``@昵称 正文``：先剥掉已有的 @昵称，再统一加一次前缀。

    正文里重复出现 ``@昵称`` 会让服务端解析出重复成员，也可能被风控当成刷屏，
    所以这里一律剥干净再补一个前缀。``name`` 为空时原样返回正文。
    """
    body = str(text or "").strip()
    target = str(name or "").strip().lstrip("@").strip()
    if not target:
        return body

    pattern = re.compile(r"@" + re.escape(target) + _AT_BOUNDARY)
    body = pattern.sub("", body)
    # 删掉 @ 之后可能留下连续空格，压成一个（只压空格与制表符，不动换行）
    body = re.sub(r"[ \t]{2,}", " ", body).strip()
    head = f"@{target}"
    return f"{head} {body}".strip() if body else head


async def resolve_owner_mid(name, search) -> int | None:
    """兜底解析：只有昵称、没有 UID 时用搜索换 UID。

    ``search`` 由调用方注入（通常是 ``self.search_bilibili_users``），
    这样本函数不需要知道 HTTP 层，也就能在测试里用假数据跑。

    只接受**昵称完全一致**的候选；找不到就返回 ``None``，
    不做「取第一个结果」的猜测。
    """
    target = str(name or "").strip().lstrip("@").strip()
    if not target or search is None:
        return None

    try:
        results = await search(target, 5)
    except Exception as exc:  # 搜索失败不该让整轮评论失败
        logger.warning(f"[BiliBot] 解析 @ 目标失败：{exc}")
        return None

    for item in results or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("uname", "")).strip() != target:
            continue
        try:
            mid = int(str(item.get("mid", "")).strip())
        except (TypeError, ValueError):
            continue
        if 0 < mid <= MID_MAX:
            return mid

    logger.warning(
        f"[BiliBot] 没找到昵称完全匹配的用户：{target!r}，本次不发真 @（避免 @ 到同名的人）"
    )
    return None


async def resolve_mention_map(owner_name, owner_mid, search=None) -> dict[str, int]:
    """组合入口：先按配置直连，配置缺 UID 时再走搜索兜底。"""
    mapping = build_mention_map(owner_name, owner_mid)
    if mapping:
        return mapping

    name = str(owner_name or "").strip().lstrip("@").strip()
    if not name:
        return {}

    mid = await resolve_owner_mid(name, search)
    return {name: mid} if mid else {}
