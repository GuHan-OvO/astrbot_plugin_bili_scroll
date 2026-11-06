"""兴趣画像：把「喜欢看什么」落成一份可编辑、可解释的数据。

三个使用场景：

- WebUI「兴趣画像」页手动编辑；
- 从人设让大模型总结一次（**只返回候选，不落盘**，由用户决定是否覆盖）；
- 选片时作为提示词素材（``TASTE_PROFILE_ENABLE`` 打开后）。

设计边界：

- 只存题材 / UP / 分区级别的倾向，不存具体视频；
- 每条都带 ``evidence``，让用户能看出这条是怎么来的；
- 画像与观看历史是两件事：``preference_signals`` 记录「看过什么」，这里记录
  「打算多看点 / 少看点」。
"""

from __future__ import annotations

import json
from typing import Any

from .config import TASTE_PROFILE_FILE
from .video_evaluation import _extract_json_object

PROFILE_VERSION = 1
"""画像文件结构版本；升级结构时在读取处做兼容。"""

MAX_INTERESTS = 20
MAX_DISLIKES = 10
MAX_SEEDS = 12
MAX_TOPIC_LEN = 40
MAX_EVIDENCE_LEN = 120
MAX_SEED_LEN = 40

SIGNAL_TYPES = ("theme", "up", "partition", "other")
"""``theme`` 题材、``up`` UP 主、``partition`` 分区、``other`` 说不清的一律归这里。"""

DEFAULT_WEIGHT = 0.5
"""模型没给权重时的默认值；权重只影响排序，不参与硬过滤。"""


class TasteProfileError(ValueError):
    """画像相关错误：模型没返回可用 JSON，或数据结构不合法。"""


def empty_profile() -> dict[str, Any]:
    """一份空画像。``generated_at`` 为空表示还没生成过。"""
    return {
        "version": PROFILE_VERSION,
        "source": "",
        "generated_at": "",
        "interests": [],
        "dislikes": [],
        "explore_seeds": [],
    }


def _clean_text(value: Any, limit: int) -> str:
    import re

    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _clean_weight(value: Any) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT
    if weight != weight:  # NaN
        return DEFAULT_WEIGHT
    return max(0.0, min(1.0, weight))


def _clean_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in SIGNAL_TYPES else "other"


def _clean_entries(value: Any, limit: int) -> list[dict[str, Any]]:
    """清洗一组 {topic,type,weight,evidence}，按 topic 去重并保留首次出现顺序。"""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            item = {"topic": item}
        if not isinstance(item, dict):
            continue
        topic = _clean_text(item.get("topic") or item.get("value"), MAX_TOPIC_LEN)
        if not topic:
            continue
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "topic": topic,
            "type": _clean_type(item.get("type")),
            "weight": _clean_weight(item.get("weight", DEFAULT_WEIGHT)),
            "evidence": _clean_text(item.get("evidence"), MAX_EVIDENCE_LEN),
        })
        if len(result) >= limit:
            break
    return result


def _clean_seeds(value: Any) -> list[str]:
    result: list[str] = []
    for item in value if isinstance(value, list) else []:
        text = _clean_text(item, MAX_SEED_LEN)
        if text and text.casefold() not in {seed.casefold() for seed in result}:
            result.append(text)
        if len(result) >= MAX_SEEDS:
            break
    return result


def normalize_profile(data: Any, *, source: str | None = None) -> dict[str, Any]:
    """把任意输入整成合法画像；非法字段一律丢弃而不是抛错。

    解析模型输出和读取磁盘都用这里，保证两条路径得到同一种结构。
    """
    value = data if isinstance(data, dict) else {}
    profile = {
        "version": PROFILE_VERSION,
        "source": _clean_text(source if source is not None else value.get("source"), 32),
        "generated_at": _clean_text(value.get("generated_at"), 32),
        "interests": _clean_entries(value.get("interests"), MAX_INTERESTS),
        "dislikes": _clean_entries(value.get("dislikes"), MAX_DISLIKES),
        "explore_seeds": _clean_seeds(value.get("explore_seeds")),
    }
    return profile


def load_profile(plugin: Any) -> dict[str, Any]:
    """读当前画像；文件不存在或损坏都返回空画像，不抛错。"""
    loader = getattr(plugin, "_load_json", None)
    raw = loader(TASTE_PROFILE_FILE, {}) if callable(loader) else {}
    return normalize_profile(raw)


def save_profile(plugin: Any, data: Any, *, source: str = "manual") -> dict[str, Any]:
    """保存画像并回读校验；返回落盘后的结构。"""
    from datetime import datetime

    profile = normalize_profile(data, source=source)
    profile["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saver = getattr(plugin, "_save_json", None)
    if not callable(saver):
        raise TasteProfileError("当前插件实例缺少 _save_json，无法保存画像")
    saver(TASTE_PROFILE_FILE, profile)
    return profile


def profile_prompt_block(profile: dict[str, Any]) -> str:
    """把画像压成一段给模型看的文字；空画像返回空字符串。"""
    interests = profile.get("interests") or []
    dislikes = profile.get("dislikes") or []
    if not interests and not dislikes:
        return ""
    lines = []
    if interests:
        ranked = sorted(interests, key=lambda item: item.get("weight", 0), reverse=True)
        topics = "、".join(str(item.get("topic") or "") for item in ranked if item.get("topic"))
        if topics:
            lines.append(f"- 多留意：{topics}")
    if dislikes:
        topics = "、".join(str(item.get("topic") or "") for item in dislikes if item.get("topic"))
        if topics:
            lines.append(f"- 少看或不看：{topics}")
    seeds = profile.get("explore_seeds") or []
    if seeds:
        lines.append(f"- 可试探的新方向：{'、'.join(str(seed) for seed in seeds)}")
    return "\n".join(lines)


def summarize_prompt(persona_text: str) -> str:
    """从人设推断偏好的提示词。只让模型做「推断」，每一条都必须给出依据。"""
    return f"""下面是一个 B站 角色的设定。请据此推断「她刷 B站 时大概会喜欢看什么」，只输出 JSON，不要解释。

要求：
- interests 写 8~15 条：每条是一个能直接提交给 B站搜索框的具体题材、作品类型、UP 类型或分区名；
- dislikes 写 2~6 条：只写设定里明确排斥、或与她的性格明显冲突的东西；
- explore_seeds 写 4~8 条：设定里没提、但符合她气质、值得试一次的方向；
- 每条都要有 evidence，引用设定里的原话或具体特征；找不到依据的条目不要写；
- 不要因为「她不熟悉某个领域」就把它写成不喜欢；
- weight 取 0~1，表示你有多确定，不是「重要性」。

角色设定：
{persona_text[:1800]}

JSON 格式：
{{"interests":[{{"topic":"","type":"theme|up|partition|other","weight":0.8,"evidence":""}}],"dislikes":[],"explore_seeds":[""]}}"""


async def summarize_from_persona(plugin: Any) -> dict[str, Any]:
    """调用大模型从人设总结画像。

    **不落盘**：调用方拿到结果后自己决定要不要覆盖（WebUI 上就是「应用」按钮）。
    """
    getter = getattr(plugin, "_get_system_prompt", None)
    if not callable(getter):
        raise TasteProfileError("当前插件实例缺少 _get_system_prompt，无法读取人设")
    persona_text = str(await getter() or "").strip()
    if not persona_text:
        raise TasteProfileError("读不到人设内容，请先在 AstrBot 里设置角色人设")

    caller = getattr(plugin, "_generation_llm_call", None) or getattr(plugin, "_llm_call", None)
    if not callable(caller):
        raise TasteProfileError("当前插件实例缺少可用的模型调用入口")
    raw = await caller(summarize_prompt(persona_text), max_tokens=1200)
    if not raw:
        raise TasteProfileError("模型没有返回内容，可稍后重试")

    try:
        data = json.loads(_extract_json_object(str(raw)))
    except Exception as exc:  # noqa: BLE001 - 模型输出不可控，统一转成可读错误
        raise TasteProfileError(f"模型输出不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise TasteProfileError("模型输出的 JSON 不是对象")

    profile = normalize_profile(data, source="persona")
    if not profile["interests"]:
        raise TasteProfileError("模型没有给出任何兴趣条目，换一个模型或补充人设后重试")
    return profile
