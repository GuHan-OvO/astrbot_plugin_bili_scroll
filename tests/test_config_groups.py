"""配置分组真源的离线测试。

这套分组要替代前端三处各自为政的口径（config.js 45 组 / app.js 18 组 / app.js 11 组），
所以这里同时守两件事：分组规则本身，以及「真实 schema 每个键都有归属」。
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.config_groups import build_groups, group_id_for, group_prefix  # noqa: E402
from core.model_options import MODEL_CONFIG_KEYS  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "_conf_schema.json"


def _field(prefix):
    return {"description": f"【{prefix}】某某配置项"}


class GroupRuleTests(unittest.TestCase):
    def test_取前缀(self):
        self.assertEqual(group_prefix(_field("账号")), "账号")
        self.assertEqual(group_prefix({"description": "没有前缀"}), "")

    def test_网络代理归基础(self):
        self.assertEqual(group_id_for(_field("网络代理")), "base")

    def test_带点的子组跟随父组(self):
        # 「高级·视觉」必须落到 模型，不能被当成独立组
        self.assertEqual(group_id_for(_field("高级·视觉")), "model")
        self.assertEqual(group_id_for(_field("高级·记忆")), "model")
        self.assertEqual(group_id_for(_field("主动看片·来源")), "proactive")
        self.assertEqual(group_id_for(_field("私信·回复")), "dm")

    def test_各组代表项(self):
        cases = {
            "账号": "base",
            "总结模型": "model",
            "生成模型": "model",
            "模型可靠性": "model",
            "联网搜索": "model",
            "回复": "reply",
            "回复筛选": "reply",
            "评论复核": "reply",
            "好感度提示词": "reply",
            "主动行为": "proactive",
            "主动看片": "proactive",
            "自主安排·上限": "proactive",
            "番剧": "proactive",
            "直播互动": "proactive",
            "日总结": "proactive",
            "视频": "proactive",
            "私信": "dm",
            "分享解析": "dm",
            "联动": "dm",
            "人设": "persona",
            "记忆隔离": "persona",
            "安全与工具": "security",
            "拉黑": "security",
            "恶意告警": "security",
        }
        for prefix, expected in cases.items():
            with self.subTest(prefix=prefix):
                self.assertEqual(group_id_for(_field(prefix)), expected)

    def test_未知前缀兜底(self):
        self.assertEqual(group_id_for(_field("从来没见过的组")), "other")
        self.assertEqual(group_id_for({"description": "没有前缀的项"}), "other")


class BuildGroupsTests(unittest.TestCase):
    def test_空分组不出现(self):
        payload = build_groups({"A": _field("账号")})
        self.assertEqual([group["id"] for group in payload["groups"]], ["base"])

    def test_key归属表覆盖全部键(self):
        schema = {"A": _field("账号"), "B": _field("私信"), "C": {"description": "无前缀"}}
        payload = build_groups(schema)
        self.assertEqual(set(payload["of_key"]), set(schema))
        ids = {group["id"] for group in payload["groups"]}
        self.assertTrue(set(payload["of_key"].values()) <= ids)

    def test_真实schema每个键都有归属(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        payload = build_groups(schema)
        self.assertEqual(set(payload["of_key"]), set(schema))
        # 保护键不在 _load_schema 下发范围里，但分组表本身也应能覆盖
        ids = {group["id"] for group in payload["groups"]}
        self.assertTrue(set(payload["of_key"].values()) <= ids)
        grouped = sum(len(group["keys"]) for group in payload["groups"])
        self.assertEqual(grouped, len(schema))

    def test_真实schema里模型选择项都归模型组(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        payload = build_groups(schema)
        for key in MODEL_CONFIG_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, schema)
                self.assertEqual(payload["of_key"][key], "model")

    def test_真实schema分组数量合理(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        payload = build_groups(schema)
        # 8 类里至少要出现 6 类，否则说明前缀表退化了
        self.assertGreaterEqual(len(payload["groups"]), 6)
        self.assertLessEqual(len(payload["groups"]), 8)


if __name__ == "__main__":
    unittest.main()
