"""与 memory_companion（「我会牢牢记住你」）的写入桥。

用途：把「她刷到 / 看完一个视频」写进她的**自我时间线**，让她在随便哪次
聊天里都能接上「我昨天刷到过一个…」。

为什么落在 ``persona_life`` 而不是 ``external_memory``：后者把记录绑在
「用户私有域」（``subject=user``、``visibility=private_pair``），语义上变成
「关于主人的事实」；而看片是**她自己的经历**。``persona_life`` 会落成
``visibility=bot_self``，MC 的 ``VisibilityPolicy.is_visible`` 对 bot_self 走
``allow_self_timeline_everywhere``（默认 True，``core/visibility.py:55-59``），
所以既不依赖 ``OWNER_QQ_UMO``，也不挑会话——任何私聊/群聊都能召回。

取实例的方式与 PC（private_companion）一致：``context.get_all_stars()`` →
``star.star_cls.memory_companion``，退路是模块级 ``get_active_bridge()``。

降级原则：MC 不在 / 桥已被注销 / 任何异常都返回 False 并记 debug 日志，
由调用方决定回退到陪伴插件，绝不让这一步把一轮看片搞挂。
"""

from __future__ import annotations

import inspect
import sys
import time
from typing import Any

from .config import PLUGIN_NAME
from .safe_logger import logger

MC_PLUGIN_NAME = "astrbot_plugin_memory_companion"
"""MC 的 StarMetadata.name，与它的 metadata.yaml 一致。"""

MC_MODULE_NAMES = (
    "data.plugins.astrbot_plugin_memory_companion.main",
    "astrbot_plugin_memory_companion.main",
)
"""模块级入口的两种导入前缀（打包/未打包）。"""

MC_BRIDGE_CACHE_SECONDS = 30.0
"""找到的桥缓存多久。MC 热重载后旧对象会失效，所以不做长缓存。"""

MC_SESSION_ID = "bilibot:watch"
"""伪会话 ID。scope 是 unknown，MC 不会拿它算归属，只当定位标签。"""

_CACHE_ATTR = "_bili_mc_bridge_cache"


def _bridge_can_write(bridge: Any) -> bool:
    """只认能写 persona_life 的桥，避免把别的对象的同名属性当桥用。"""
    return callable(getattr(bridge, "record_persona_life", None))


def _bridge_is_live(bridge: Any) -> bool:
    """没有 lifecycle 方法的旧版按「可用」处理；有就必须报 active=True。"""
    lifecycle = getattr(bridge, "bridge_lifecycle_status", None)
    if not callable(lifecycle):
        return True
    try:
        status = lifecycle()
    except Exception:
        return False
    return isinstance(status, dict) and status.get("active") is True


def _bridge_from_object(candidate: Any) -> Any | None:
    if candidate is None:
        return None
    # 实例属性优先于模块级 getter：MC 在 private_companion_bridge.enabled=false 时
    # 会把模块级 _ACTIVE_BRIDGE / get_active_bridge() 置空，但 star_cls 上的
    # memory_companion 实例仍在（MC main.py:60 与 71-72）。只试 getter 会误判「未安装」。
    for attr in ("memory_companion", "memory_companion_bridge", "bridge", "_ACTIVE_BRIDGE"):
        bridge = getattr(candidate, attr, None)
        if bridge is None:
            continue
        if _bridge_can_write(bridge) and _bridge_is_live(bridge):
            return bridge
    return None


def _bridge_from_module(module: Any) -> Any | None:
    if module is None:
        return None
    for getter_name in ("get_active_bridge", "get_memory_companion_bridge"):
        getter = getattr(module, getter_name, None)
        if not callable(getter):
            continue
        try:
            bridge = getter()
        except Exception:
            bridge = None
        if bridge is not None and _bridge_can_write(bridge) and _bridge_is_live(bridge):
            return bridge
    return _bridge_from_object(module)


async def _resolve_stars(context: Any) -> list:
    """取已加载插件列表。AstrBot 各版本这里可能是同步或协程，两种都吃下。"""
    getter = getattr(context, "get_all_stars", None)
    if not callable(getter):
        return []
    try:
        stars = getter()
        if inspect.isawaitable(stars):
            stars = await stars
        return list(stars or [])
    except Exception:
        return []


def _find_uncached(context: Any, stars: list) -> Any | None:
    for metadata in stars:
        if str(getattr(metadata, "name", "") or "") != MC_PLUGIN_NAME:
            continue
        if not bool(getattr(metadata, "activated", True)):
            continue
        bridge = _bridge_from_object(getattr(metadata, "star_cls", None))
        if bridge is not None:
            return bridge
        bridge = _bridge_from_module(getattr(metadata, "module", None))
        if bridge is not None:
            return bridge
    for module_name in MC_MODULE_NAMES:
        bridge = _bridge_from_module(sys.modules.get(module_name))
        if bridge is not None:
            return bridge
    return None


async def find_mc_bridge(context: Any) -> Any | None:
    """拿到 MC 的 MemoryCompanionBridge；没装或未激活就返回 None。

    缓存挂在 context 上（不是模块全局），插件热重载后新 context 自然重新找。
    """
    cached = getattr(context, _CACHE_ATTR, None)
    now = time.monotonic()
    if isinstance(cached, tuple) and len(cached) == 2:
        bridge, expires_at = cached
        if bridge is not None and now < float(expires_at) and _bridge_is_live(bridge):
            return bridge
    bridge = _find_uncached(context, await _resolve_stars(context))
    try:
        setattr(context, _CACHE_ATTR, (bridge, now + MC_BRIDGE_CACHE_SECONDS))
    except Exception:
        pass
    return bridge


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _importance_for_score(score: Any) -> float:
    """评分越高越值得记住；限制在 0.35~0.80 之间，别让普通消遣挤掉重要记忆。"""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.50
    value = max(0.0, min(10.0, value))
    return round(0.30 + value / 10.0 * 0.50, 2)


def build_watch_memory_text(entry: dict) -> str:
    """把一条观看记录写成她自己的一句自述（第一人称，不罗列要点）。

    用 entry 里她自己的评分与点评，不再额外调 LLM——省一次调用，也避免
    「记忆内容取决于模型当时是否可用」这种不可复现的输入。
    """
    title = _clip(entry.get("title"), 80)
    if not title:
        return ""
    parts = [f"我今天在B站刷到一个视频：《{title}》"]
    tname = _clip(entry.get("tname"), 20)
    up_name = _clip(entry.get("up_name"), 30)
    tail = "，".join(item for item in (f"{tname}区" if tname else "", f"UP主是{up_name}" if up_name else "") if item)
    if tail:
        parts.append(tail)
    text = "，".join(parts) + "。"
    score = entry.get("score")
    if score not in (None, ""):
        text += f" 我给了 {score}/10。"
    comment = _clip(entry.get("comment"), 80)
    if comment:
        text += f" 我当时觉得：{comment}"
    review = _clip(entry.get("review"), 60)
    if review and review != comment:
        text += f" 复核时又想到：{review}"
    return text.strip()


def _watch_tags(entry: dict) -> list[str]:
    tags = ["bilibili", "watch", "persona_life"]
    tname = _clip(entry.get("tname"), 20)
    if tname:
        tags.append(tname)
    bvid = _clip(entry.get("bvid"), 20)
    if bvid:
        tags.append(bvid)
    return tags


def _watch_metadata(entry: dict) -> dict:
    """只放可核对的字段；不做 sanitize 之外的加工，避免和 MC 的清洗重复。"""
    bvid = _clip(entry.get("bvid"), 20)
    metadata = {
        "bvid": bvid,
        "title": _clip(entry.get("title"), 120),
        "up_name": _clip(entry.get("up_name"), 60),
        "up_mid": _clip(entry.get("up_mid"), 30),
        "partition": _clip(entry.get("tname"), 30),
        "score": entry.get("score"),
        "source": _clip(entry.get("source"), 40),
        "query_anchors": ["B站", "刷视频", "看了什么", "最近看的"],
    }
    if bvid:
        metadata["url"] = f"https://www.bilibili.com/video/{bvid}"
    return {key: value for key, value in metadata.items() if value not in (None, "")}


async def remember_watch_entry(context: Any, entry: dict, *, generated_text: str = "") -> bool:
    """把一次观看写进她的自我时间线。

    ``generated_text`` 可选：调用方若已有「她的一句感受」（例如陪伴插件用她
    的人格生成过），优先用它当正文；否则用 ``build_watch_memory_text``。
    同一 bvid 用固定 memory_id，MC 侧是 upsert + 内容指纹去重，重复注入不会
    堆出多条。
    """
    bridge = await find_mc_bridge(context)
    if bridge is None:
        return False
    recorder = getattr(bridge, "record_persona_life", None)
    if not callable(recorder):
        return False

    entry = entry if isinstance(entry, dict) else {}
    content = _clip(generated_text, 400) or build_watch_memory_text(entry)
    if not content:
        logger.debug("[BiliBot] 观看记忆正文为空，跳过写入")
        return False

    bvid = _clip(entry.get("bvid"), 20)
    payload = {
        "content": content,
        "scope": "unknown",
        "session_id": MC_SESSION_ID,
        "source_plugin": PLUGIN_NAME,
        "confidence": 0.85,
        "importance": _importance_for_score(entry.get("score")),
        "tags": _watch_tags(entry),
        "metadata": _watch_metadata(entry),
    }
    if bvid:
        payload["memory_id"] = f"bilibot_watch_{bvid}"
    try:
        memory_id = await recorder(**payload)
    except Exception as exc:
        logger.debug(f"[BiliBot] 写入记忆插件失败（不影响本轮）：{exc}")
        return False
    # record_persona_life 返回 str memory_id；空串说明 MC 内部没落库。
    if isinstance(memory_id, str) and not memory_id.strip():
        logger.debug("[BiliBot] 记忆插件未返回 memory_id，按未写入处理")
        return False
    return True
