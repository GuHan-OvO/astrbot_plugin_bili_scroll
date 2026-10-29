"""把 AstrBot 已配置的模型整理成前端可直接渲染的清单。

BiliBot 的模型选择项（``*_PROVIDER_ID``）以前只能手填字符串，用户必须自己
去面板里抄 provider id。这里把宿主侧的 provider 统一导出，供配置页做成下拉。

两条数据来源缺一不可：

* ``context.get_all_providers()`` 等只返回 **已启用** 的 provider ——
  ``ProviderManager.load_provider`` 在 ``enable`` 为假时直接 return，
  禁用项永远不会被实例化；
* ``provider_manager.providers_config`` 是配置真源，含禁用项与未加载项，
  但 chat 条目的 ``provider_type`` 往往是空串（类型在 ``provider_sources`` 里），
  必须按 ``provider_source_id`` 回填，否则按能力过滤会得到 0 条。

**安全约束**：``provider_config`` 里的 ``key`` / ``embedding_api_key`` /
``rerank_api_key`` 是明文（``manager._resolve_env_key_list`` 会把 ``$ENV``
解析后写回同一个字典），所以本模块只挑 ``id / model / provider_type /
enabled / loaded`` 几个字段，任何情况下都不把 provider 配置原文带出去。
"""
from __future__ import annotations

from typing import Any

from astrbot.api import logger

# 前端渲染顺序与中文名。AstrBot 的 ProviderType 枚举见
# astrbot/core/provider/entities.py（chat_completion / speech_to_text /
# text_to_speech / embedding / rerank），这里只映射插件会用到的那几种。
CAPABILITIES: tuple[tuple[str, str], ...] = (
    ("chat", "对话模型"),
    ("embedding", "向量模型"),
    ("rerank", "重排序模型"),
    ("tts", "语音合成"),
    ("stt", "语音识别"),
)

# ProviderType.value -> 前端能力标签
_TYPE_TO_CAPABILITY = {
    "chat_completion": "chat",
    "embedding": "embedding",
    "rerank": "rerank",
    "text_to_speech": "tts",
    "speech_to_text": "stt",
}

# 配置键 -> 该键需要哪一类模型。模型独立配置页照这张表分组，
# 避免前端再维护一份能力映射。
MODEL_CONFIG_KEYS: dict[str, str] = {
    "LLM_PROVIDER_ID": "chat",
    "SUMMARY_PROVIDER_ID": "chat",
    "GENERATION_PROVIDER_ID": "chat",
    "SCHEDULE_PLAN_PROVIDER_ID": "chat",
    "VIDEO_VISION_PROVIDER_ID": "chat",
    "IMAGE_VISION_PROVIDER_ID": "chat",
    "WEB_SEARCH_JUDGE_PROVIDER_ID": "chat",
    "EMBED_PROVIDER_ID": "embedding",
}

# 能取到实例化 provider 的 Context 方法（每个返回 list[Provider]）
_INSTANCE_GETTERS: dict[str, str] = {
    "chat": "get_all_providers",
    "stt": "get_all_stt_providers",
    "tts": "get_all_tts_providers",
    "embedding": "get_all_embedding_providers",
}

# 直连型 provider 在配置里的模型字段名
_MODEL_FIELDS = ("model", "embedding_model", "rerank_model")


def _meta_of(obj: Any):
    getter = getattr(obj, "meta", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:  # 单个 provider 元信息异常不应拖垮整张清单
        return None


def _capability_of(meta: Any) -> str:
    raw = getattr(meta, "provider_type", None)
    value = getattr(raw, "value", None) or (str(raw) if raw is not None else "")
    return _TYPE_TO_CAPABILITY.get(str(value).strip(), "")


def _model_of(provider: Any, config_entry: dict | None = None) -> str:
    meta = _meta_of(provider) if provider is not None else None
    model = getattr(meta, "model", None)
    if model:
        return str(model)
    if config_entry:
        for field in _MODEL_FIELDS:
            value = config_entry.get(field)
            if value:
                return str(value)
    return ""


def _item(pid: str, model: str, provider_type: str, *, enabled: bool, loaded: bool, dim: Any = None) -> dict:
    item = {
        "id": pid,
        "model": model,
        "provider_type": provider_type,
        "enabled": bool(enabled),
        "loaded": bool(loaded),
    }
    if isinstance(dim, int) and dim > 0:
        item["dim"] = dim
    return item


def _instance_items(context: Any) -> dict[str, list[dict]]:
    """取已实例化（即已启用）的 provider。"""
    buckets: dict[str, list[dict]] = {cap: [] for cap, _ in CAPABILITIES}
    manager = getattr(context, "provider_manager", None)

    for capability, getter_name in _INSTANCE_GETTERS.items():
        getter = getattr(context, getter_name, None)
        if not callable(getter):
            continue
        try:
            providers = getter() or []
        except Exception as exc:
            logger.debug(f"[BiliBot] 读取 {capability} provider 列表失败：{exc}")
            continue
        for provider in providers:
            meta = _meta_of(provider)
            pid = str(getattr(meta, "id", "") or "").strip()
            if not pid:
                continue
            provider_type = str(getattr(meta, "type", "") or "")
            dim = None
            if capability == "embedding":
                dim_getter = getattr(provider, "get_dim", None)
                if callable(dim_getter):
                    try:
                        dim = dim_getter()
                    except Exception:
                        dim = None
            buckets[capability].append(
                _item(pid, _model_of(provider), provider_type, enabled=True, loaded=True, dim=dim)
            )

    # rerank 没有对应的 Context getter，只能直接读管理器属性。
    rerank = getattr(manager, "rerank_provider_insts", None) or []
    for provider in rerank:
        meta = _meta_of(provider)
        pid = str(getattr(meta, "id", "") or "").strip()
        if not pid:
            continue
        buckets["rerank"].append(
            _item(pid, _model_of(provider), str(getattr(meta, "type", "") or ""), enabled=True, loaded=True)
        )
    return buckets


def _config_items(context: Any) -> dict[str, list[dict]]:
    """取配置里声明的全部 provider（含禁用 / 未加载）。"""
    buckets: dict[str, list[dict]] = {cap: [] for cap, _ in CAPABILITIES}
    manager = getattr(context, "provider_manager", None)
    entries = getattr(manager, "providers_config", None) or []

    source_types: dict[str, str] = {}
    sources = getattr(manager, "provider_sources_config", None) or []
    for source in sources:
        if not isinstance(source, dict):
            continue
        sid = str(source.get("id") or "").strip()
        if sid:
            source_types[sid] = str(source.get("provider_type") or "").strip()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("id") or "").strip()
        if not pid:
            continue
        provider_type = str(entry.get("provider_type") or "").strip()
        if not provider_type:
            # chat 条目自身不带类型，类型记在 provider_source 上。
            provider_type = source_types.get(str(entry.get("provider_source_id") or "").strip(), "")
        capability = _TYPE_TO_CAPABILITY.get(provider_type, "chat")
        if capability not in buckets:
            continue
        buckets[capability].append(
            _item(
                pid,
                _model_of(None, entry),
                provider_type,
                enabled=bool(entry.get("enable", True)),
                loaded=False,
            )
        )
    return buckets


def _default_chat_provider(context: Any) -> str:
    getter = getattr(context, "get_using_provider", None)
    if not callable(getter):
        return ""
    try:
        provider = getter()
    except Exception as exc:
        logger.debug(f"[BiliBot] 读取默认对话模型失败：{exc}")
        return ""
    meta = _meta_of(provider)
    return str(getattr(meta, "id", "") or "").strip()


def collect_model_options(context: Any) -> dict:
    """汇总宿主侧模型清单。

    返回结构（前端契约，改动需同步 ``docs/frontend-spec-model-config.md``）::

        {
          "groups": [{"capability": "chat", "label": "对话模型", "items": [...]}],
          "config_keys": {"LLM_PROVIDER_ID": "chat", ...},
          "default_chat": "<provider id 或空串>"
        }

    每项 ``item`` 只含 ``id / model / provider_type / enabled / loaded``
    （向量模型可能多一个 ``dim``）；**不含任何密钥字段**。
    """
    loaded = _instance_items(context)
    declared = _config_items(context)

    groups: list[dict] = []
    for capability, label in CAPABILITIES:
        merged: dict[str, dict] = {}
        for item in declared[capability]:
            merged[item["id"]] = item
        for item in loaded[capability]:
            existing = merged.get(item["id"])
            if existing is None:
                merged[item["id"]] = item
            else:
                # 同一 id 同时出现在配置与实例里：以实例的模型名为准，
                # 但保留配置里的启用状态（禁用项不可能被实例化）。
                existing["loaded"] = True
                if item["model"]:
                    existing["model"] = item["model"]
                if item.get("dim"):
                    existing["dim"] = item["dim"]
        items = list(merged.values())
        # 能用的排前面，其次按 id 稳定排序，避免每次刷新顺序抖动。
        items.sort(key=lambda one: (not one["enabled"], one["id"]))
        groups.append({"capability": capability, "label": label, "items": items})

    return {
        "groups": groups,
        "config_keys": dict(MODEL_CONFIG_KEYS),
        "default_chat": _default_chat_provider(context),
    }
