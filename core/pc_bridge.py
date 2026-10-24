"""与 private_companion 7.0.0 的联动桥。

7.0.0 把对外能力收在 ``插件实例.extension_api``（``UnifiedCompanionExtensionAPI``），
本模块只用其中三个方法：

- ``generate_reality_touch_text(prompt)``   用「她」的人格生成一句话
- ``send_reality_touch_chat(umo, text)``    走「她」的通道发出去
- ``record_reality_touch_output(user_id, text)``  让她记得自己说过这句

取实例的方式与 PC 自己一致：``context.get_all_stars()`` → ``star.star_cls.extension_api``。
**每次都重新取**：7.0.0 热重载后旧引用会失效。

降级原则：任何一步失败都返回 None/False，由调用方回退到「本插件自己的 QQ 直发」，
绝不让联动把一轮推荐整个搞挂。
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger

PC_PLUGIN_NAME = "astrbot_plugin_private_companion"
"""PC 的插件名（StarMetadata.name），与它的 metadata.yaml 一致。"""

PC_API_VERSION = "companion.product.v1"
"""7.0.0 的 UnifiedCompanionExtensionAPI.api_version；版本不符就不认，避免按旧语义瞎调。"""

GENERATE_TIMEOUT = 15.0
"""生成一句话的超时（她的生成里可能还有模型调用，别给太短）。"""


def find_pc_api(context) -> Any | None:
    """在当前已加载的插件里找 PC 的只读门面；找不到返回 None。"""
    try:
        stars = context.get_all_stars() or []
    except Exception as exc:
        logger.debug(f"[BiliBot] 枚举插件失败，无法联动陪伴：{exc}")
        return None

    for star in stars:
        if getattr(star, "name", "") != PC_PLUGIN_NAME:
            continue
        api = getattr(getattr(star, "star_cls", None), "extension_api", None)
        if api is None:
            continue
        if str(getattr(api, "api_version", "")) != PC_API_VERSION:
            logger.debug(
                f"[BiliBot] 陪伴插件版本不匹配（{getattr(api, 'api_version', '?')}），跳过联动"
            )
            continue
        return api
    return None


def user_id_from_umo(umo: str) -> str:
    """从 ``platform:MessageType:session_id`` 里取 session_id（QQ 号）。"""
    parts = str(umo or "").split(":", 2)
    return parts[2].strip() if len(parts) == 3 else ""


async def compose_with_persona(api, prompt: str) -> str | None:
    """让她用自己的口吻生成一句话；不可用/超时/空结果都返回 None。"""
    generate = getattr(api, "generate_reality_touch_text", None)
    if not callable(generate):
        return None
    try:
        text = await asyncio.wait_for(generate(prompt), timeout=GENERATE_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("[BiliBot] 陪伴生成文案超时，改用本插件模板")
        return None
    except Exception as exc:
        logger.warning(f"[BiliBot] 陪伴生成文案失败，改用本插件模板：{exc}")
        return None

    text = str(text or "").strip()
    return text or None


async def deliver_via_pc(api, umo: str, text: str) -> bool:
    """走她的通道发出去，并让她记住自己说过。失败返回 False。"""
    send = getattr(api, "send_reality_touch_chat", None)
    if not callable(send) or not umo or not text:
        return False
    try:
        ok = await send(umo, text)
    except Exception as exc:
        logger.warning(f"[BiliBot] 陪伴通道发送失败：{exc}")
        return False
    if not ok:
        return False

    # 记录失败不影响已发出的消息，所以单独兜住
    record = getattr(api, "record_reality_touch_output", None)
    user_id = user_id_from_umo(umo)
    if callable(record) and user_id:
        try:
            await record(user_id, text)
        except Exception as exc:
            logger.debug(f"[BiliBot] 陪伴记录输出失败（不影响已发出的消息）：{exc}")
    return True


async def share_via_pc(context, umo: str, prompt: str, fallback_text: str) -> tuple[bool, str]:
    """完整桥接：取实例 → 生成 → 发送。

    返回 ``(是否已通过陪伴发出, 实际发出的文本)``。
    第一项为 False 时调用方应回退到自己的直发。
    """
    api = find_pc_api(context)
    if api is None:
        return False, fallback_text

    text = await compose_with_persona(api, prompt) or fallback_text
    if await deliver_via_pc(api, umo, text):
        logger.info("[BiliBot] ✉️ 已通过陪伴插件的人格与通道发出")
        return True, text
    return False, text
