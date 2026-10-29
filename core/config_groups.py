"""配置分组真源。

历史包袱：同一份 ``_conf_schema.json`` 被三套互不相同的分组口径解释过 ——

* ``pages/config/config.js:57-65`` 按 ``description`` 的 ``【…】`` 前缀分 45 组；
* ``pages/bilibot/app.js:2321`` 的 ``ALL_CONFIG_GROUPS`` 是 18 组；
* ``pages/bilibot/app.js:2240`` 的 ``BASIC_GROUP_ORDER`` 是 11 组。

于是「基础配置」和「全部配置」两个视图对同一批键给出不同归属，改一处就会
和另一处对不上。本模块把它们收敛成**一套**定义，由 ``GET config/groups``
下发给前端，前端只负责渲染。

分组规则：取 ``description`` 的 ``【…】`` 前缀，按 ``GROUP_DEFINITIONS``
里的 ``prefixes`` 做**最长前缀匹配**（所以 ``高级·视觉`` 命中「高级·视觉」
而不是「高级」），未命中任何前缀的进 ``other``。没有前缀的键同样进 ``other``。
"""
from __future__ import annotations

import re
from typing import Any

from .model_options import MODEL_CONFIG_KEYS

_GROUP_RE = re.compile(r"^【([^】]+)】")

# 模型选择项在 schema 里的前缀并不统一（LLM_PROVIDER_ID 挂在【人设】、
# SCHEDULE_PLAN_PROVIDER_ID 挂在【自主安排】、其余散在【高级·视觉】【联网搜索】），
# 只按前缀分组会让「模型」页一半是空的。所以这些键显式归入 model 组，
# 优先级高于前缀规则 —— 这也是「模型与人设分开」这个细分的实际含义。
KEY_OVERRIDES: dict[str, str] = {key: "model" for key in MODEL_CONFIG_KEYS}

GROUP_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "base",
        "label": "基础与账号",
        "hint": "登录态、代理和兼容开关；平时基本不用动。",
        "prefixes": ("账号", "网络代理", "兼容"),
    },
    {
        "id": "model",
        "label": "模型与能力",
        "hint": "各类模型的选择与接入；每项都优先用 AstrBot 已配置的模型。",
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
        "hint": "自己刷视频、看番、直播、发动态、写总结和安排作息。",
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
        "hint": "工具白名单、拉黑和恶意输入告警。",
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
