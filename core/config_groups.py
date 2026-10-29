"""配置分组真源。

历史情况：同一份 ``_conf_schema.json`` 曾被三套互不一致的分组口径解释 ——

* ``pages/config/config.js:57-65`` 按 ``description`` 的 ``【…】`` 前缀分出 45 组；
* ``pages/bilibot/app.js:2321`` 的 ``ALL_CONFIG_GROUPS`` 为 18 组；
* ``pages/bilibot/app.js:2240`` 的 ``BASIC_GROUP_ORDER`` 为 11 组。

这使「基础配置」与「全部配置」两个视图对同一批键的归属不一致，任一处调整都会
与另一处产生偏差。本模块将其统一为**唯一**定义，由 ``GET config/groups`` 下发，
前端仅负责渲染。

分组规则：取 ``description`` 的 ``【…】`` 前缀，在 ``GROUP_DEFINITIONS`` 的
``prefixes`` 中做**最长前缀匹配**（例如 ``主动看片·来源`` 命中 ``主动看片``）；
未命中任何前缀的配置项归入 ``other``，无前缀者亦归入 ``other``。
"""
from __future__ import annotations

import re
from typing import Any

from .model_options import MODEL_CONFIG_KEYS

_GROUP_RE = re.compile(r"^【([^】]+)】")

# 模型选择项在 schema 中的前缀并不统一（LLM_PROVIDER_ID 位于【人设】、
# SCHEDULE_PLAN_PROVIDER_ID 位于【自主安排】、其余分散于【高级·视觉】【联网搜索】），
# 仅按前缀分组会导致模型分组内容缺失。故这些键显式归入 model 组，
# 优先级高于前缀规则；这也正是「模型与人设分离」这一细分的实际含义。
KEY_OVERRIDES: dict[str, str] = {key: "model" for key in MODEL_CONFIG_KEYS}

GROUP_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "base",
        "label": "基础与账号",
        "hint": "登录状态、网络代理与兼容性开关，通常无需调整。",
        "prefixes": ("账号", "网络代理", "兼容"),
    },
    {
        "id": "model",
        "label": "模型与能力",
        "hint": "各类模型的选择与接入，优先使用 AstrBot 中已启用的模型。",
        "prefixes": (
            "高级",
            "总结模型",
            "生成模型",
            "模型可靠性",
            "联网搜索",
        ),
    },
    {
        "id": "reply",
        "label": "回复与互动",
        "hint": "评论回复、筛选口径、好感度与心情提示词。",
        "prefixes": ("回复", "好感度", "心情", "评论复核", "给主人推荐"),
    },
    {
        "id": "proactive",
        "label": "主动与日常",
        "hint": "主动刷视频、追番、直播互动、动态发布、总结与作息安排。",
        "prefixes": (
            "主动行为",
            "主动看片",
            "关注动态巡视",
            "番剧",
            "直播",
            "动态",
            "日总结",
            "周总结",
            "总结",
            "自主安排",
            "自主查询",
            "行为调度",
            "固定计划",
            "作息",
            "演化",
            "性格演化",
            "观影日志",
            "视频",
        ),
    },
    {
        "id": "dm",
        "label": "私信与分享",
        "hint": "B站私信的监听、回复、分享解析与跨端活动。",
        "prefixes": ("私信", "分享解析", "跨端活动与分享", "联动"),
    },
    {
        "id": "persona",
        "label": "人格与记忆",
        "hint": "人设来源和记忆隔离边界。",
        "prefixes": ("人设", "记忆隔离"),
    },
    {
        "id": "security",
        "label": "安全",
        "hint": "工具白名单、自动拉黑与恶意输入告警。",
        "prefixes": ("安全与工具", "拉黑", "恶意告警", "特别关注"),
    },
)

OTHER_GROUP = {
    "id": "other",
    "label": "其它",
    "hint": "没能归入上面任何一组的配置项。",
}


def group_prefix(field: dict) -> str:
    """取一条配置项 ``description`` 里的分组前缀，没有则返回空串。"""
    match = _GROUP_RE.match(str(field.get("description") or "").strip())
    return match.group(1).strip() if match else ""


def group_id_for(field: dict, key: str | None = None) -> str:
    """把一条配置项映射到分组 id。

    先看 ``KEY_OVERRIDES``（显式键归属），再按 ``【…】`` 前缀做最长匹配。
    """
    if key and key in KEY_OVERRIDES:
        return KEY_OVERRIDES[key]
    prefix = group_prefix(field)
    if not prefix:
        return OTHER_GROUP["id"]
    best_id = OTHER_GROUP["id"]
    best_length = 0
    for definition in GROUP_DEFINITIONS:
        for candidate in definition["prefixes"]:
            if prefix.startswith(candidate) and len(candidate) > best_length:
                best_id = definition["id"]
                best_length = len(candidate)
    return best_id


def build_groups(schema: dict[str, dict]) -> dict:
    """按分组真源给 schema 分桶。

    返回（前端契约，改动需同步 ``docs/frontend-spec-model-config.md``）::

        {
          "groups": [
            {"id": "base", "label": "基础与账号", "hint": "...",
             "keys": ["SESSDATA", ...], "prefixes": [...]}
          ],
          "of_key": {"SESSDATA": "base", ...}
        }

    ``of_key`` 让前端不必再自己解析 ``【…】`` 前缀；``groups`` 的顺序即
    建议的 tab 顺序。空分组不会出现在 ``groups`` 里。
    """
    buckets: dict[str, list[str]] = {definition["id"]: [] for definition in GROUP_DEFINITIONS}
    buckets[OTHER_GROUP["id"]] = []
    of_key: dict[str, str] = {}

    for key, field in schema.items():
        if not isinstance(field, dict):
            continue
        gid = group_id_for(field, key)
        of_key[key] = gid
        buckets.setdefault(gid, []).append(key)

    groups: list[dict] = []
    for definition in (*GROUP_DEFINITIONS, OTHER_GROUP):
        keys = buckets.get(definition["id"]) or []
        if not keys:
            continue
        groups.append(
            {
                "id": definition["id"],
                "label": definition["label"],
                "hint": definition["hint"],
                "keys": keys,
                "prefixes": list(definition.get("prefixes") or ()),
            }
        )
    return {"groups": groups, "of_key": of_key}
