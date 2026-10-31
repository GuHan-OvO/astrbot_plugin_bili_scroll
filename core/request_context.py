"""把短时上下文注入本次 LLM 请求，不污染系统提示词与会话历史。

AstrBot 每轮都会用 ``ProviderRequest.assemble_context()`` 重新组装 user 消息，
会话历史则由 ``run_context.messages`` 落盘（``_save_to_history``）。过去这里用过两种
注入方式，都有副作用：

- 改 ``req.system_prompt``：它是模型收到的第一条 system 消息，注入每轮都变的文本
  （昵称、上一条视频标题）会让服务端前缀缓存失效，也破坏「系统提示词 = 稳定人格」的分层。
- 把块拼进 ``req.prompt``：它会随 ``assemble_context()`` 进入本轮 user 消息，进而被
  ``_save_to_history`` 写进会话历史；每轮注入一次就在历史里叠加一份。

AstrBot 为此提供了 ``req.extra_user_content_parts``：这些片段会被并进本轮 user 内容
（排在用户原话之后），而 ``ContentPart.mark_as_temp()`` 会给它打上 ``_no_save`` 标记，
``dump_messages_with_checkpoints()`` 在落盘前逐个 part 过滤
（``astrbot/core/agent/message.py:350-355``），因此临时内容只发给模型、不进历史。

注意两点：

- ``mark_as_temp`` 在 ``astrbot.core.*`` 内部模块，不是 ``astrbot.api.*`` 公共 API，
  所以导入与调用都做了保护；缺这个机制时注入仍生效，只是退化回「会进历史」。
- provider 若配置了 ``modalities`` 且并非图片音频全支持，会走 provider 专用的
  ``assemble_context``，那条路径只取 ``TextPart.text``、会丢掉 ``_no_save``
  （上游行为），此时同样退化为「注入生效但会进历史」。默认未配置 ``modalities`` 时走
  ``ProviderRequest.assemble_context()``，``_no_save`` 完整保留。
"""

from __future__ import annotations

from astrbot.api import logger


def _get_text_part():
    """延迟导入 TextPart。

    模块级一次导入的问题：若首次导入发生在 astrbot 尚未就绪的时刻（例如测试里用桩模块
    替换 sys.modules 的顺序问题），就会永久退回「不支持注入」。每次注入重新取一次，
    Python 的模块缓存让这个开销可以忽略。
    """
    try:  # 内部 API；缺失时退化为不注入临时标记，绝不回退到改 system_prompt
        from astrbot.core.agent.message import TextPart
    except Exception:  # pragma: no cover - 取决于 AstrBot 版本与导入时机
        return None
    return TextPart


def build_temp_text_part(text):
    """构造一个「只发给模型、不写历史」的文本片段；环境不支持时返回 None。"""
    value = (text or "").strip()
    text_part_cls = _get_text_part()
    if not value or text_part_cls is None:
        return None
    try:
        part = text_part_cls(text=value)
    except Exception as exc:  # pragma: no cover - 构造失败等同于不支持
        logger.debug(f"[BiliBot] 临时上下文片段构造失败: {exc}")
        return None
    mark = getattr(part, "mark_as_temp", None)
    if callable(mark):
        try:
            mark()
        except Exception as exc:  # pragma: no cover - 标记失败时仍可注入
            logger.debug(f"[BiliBot] 临时上下文标记失败: {exc}")
    return part


def inject_temp_context(req, block):
    """把临时上下文追加到本次请求；返回是否注入成功。"""
    part = build_temp_text_part(block)
    if part is None:
        return False
    parts = getattr(req, "extra_user_content_parts", None)
    if not isinstance(parts, list):
        return False
    parts.append(part)
    return True
