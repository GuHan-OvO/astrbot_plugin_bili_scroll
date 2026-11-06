"""兴趣画像的离线测试：清洗、读写、从人设总结。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.config import TASTE_PROFILE_FILE  # noqa: E402
from core.taste_profile import (  # noqa: E402
    MAX_DISLIKES,
    MAX_INTERESTS,
    MAX_SEEDS,
    TasteProfileError,
    empty_profile,
    load_profile,
    normalize_profile,
    profile_prompt_block,
    save_profile,
    summarize_from_persona,
    summarize_prompt,
)


class _FakePlugin:
    """只实现画像模块实际用到的两个存取方法。"""

    def __init__(self, store=None):
        self.store = dict(store or {})

    def _load_json(self, path, default):
        return self.store.get(path, default)

    def _save_json(self, path, value):
        self.store[path] = value


class _PersonaPlugin(_FakePlugin):
    def __init__(self, *, persona="她喜欢独立游戏和木工", reply="", raises=None):
        super().__init__()
        self.persona = persona
        self.reply = reply
        self.raises = raises
        self.calls = []

    async def _get_system_prompt(self):
        return self.persona

    async def _generation_llm_call(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.raises:
            raise self.raises
        return self.reply


class NormalizeTests(unittest.TestCase):
    def test_空输入得到空画像(self):
        profile = normalize_profile(None)
        self.assertEqual(profile["interests"], [])
        self.assertEqual(profile["dislikes"], [])
        self.assertEqual(profile["explore_seeds"], [])
        self.assertEqual(profile["version"], empty_profile()["version"])

    def test_字符串条目也能收(self):
        profile = normalize_profile({"interests": ["独立游戏", "  木工  "]})
        self.assertEqual([item["topic"] for item in profile["interests"]], ["独立游戏", "木工"])
        self.assertEqual(profile["interests"][0]["type"], "other")

    def test_非法类型归other(self):
        profile = normalize_profile({"interests": [{"topic": "x", "type": "不存在的类型"}]})
        self.assertEqual(profile["interests"][0]["type"], "other")

    def test_权重被夹到0到1(self):
        profile = normalize_profile({
            "interests": [
                {"topic": "a", "weight": 5},
                {"topic": "b", "weight": -3},
                {"topic": "c", "weight": "坏值"},
                {"topic": "d", "weight": float("nan")},
            ]
        })
        weights = {item["topic"]: item["weight"] for item in profile["interests"]}
        self.assertEqual(weights["a"], 1.0)
        self.assertEqual(weights["b"], 0.0)
        self.assertEqual(weights["c"], 0.5)
        self.assertEqual(weights["d"], 0.5)

    def test_同名去重且保留首次(self):
        profile = normalize_profile({
            "interests": [{"topic": "独立游戏"}, {"topic": "独立游戏"}, {"topic": "INDEPENDENT"}]
        })
        self.assertEqual(len(profile["interests"]), 2, "同名只留一条，不同名各留一条")
        profile2 = normalize_profile({"interests": [{"topic": "木工"}, {"topic": "木工"}]})
        self.assertEqual(len(profile2["interests"]), 1)

    def test_数量上限(self):
        profile = normalize_profile({
            "interests": [{"topic": f"t{i}"} for i in range(MAX_INTERESTS + 8)],
            "dislikes": [{"topic": f"d{i}"} for i in range(MAX_DISLIKES + 8)],
            "explore_seeds": [f"s{i}" for i in range(MAX_SEEDS + 8)],
        })
        self.assertEqual(len(profile["interests"]), MAX_INTERESTS)
        self.assertEqual(len(profile["dislikes"]), MAX_DISLIKES)
        self.assertEqual(len(profile["explore_seeds"]), MAX_SEEDS)

    def test_超长主题被截断(self):
        profile = normalize_profile({"interests": [{"topic": "长" * 200}]})
        self.assertLessEqual(len(profile["interests"][0]["topic"]), 40)


class PromptBlockTests(unittest.TestCase):
    def test_空画像返回空串(self):
        self.assertEqual(profile_prompt_block(empty_profile()), "")

    def test_正常画像包含三类(self):
        profile = normalize_profile({
            "interests": [{"topic": "独立游戏", "weight": 0.9}],
            "dislikes": [{"topic": "标题党"}],
            "explore_seeds": ["语言学"],
        })
        block = profile_prompt_block(profile)
        self.assertIn("多留意", block)
        self.assertIn("独立游戏", block)
        self.assertIn("少看或不看", block)
        self.assertIn("可试探的新方向", block)
        self.assertIn("语言学", block)


class SaveLoadTests(unittest.TestCase):
    def test_读不到文件返回空画像(self):
        profile = load_profile(_FakePlugin())
        self.assertEqual(profile["interests"], [])

    def test_损坏数据不抛错(self):
        plugin = _FakePlugin({TASTE_PROFILE_FILE: "这不是对象"})
        self.assertEqual(load_profile(plugin)["interests"], [])

    def test_保存后能读回且带时间戳(self):
        plugin = _FakePlugin()
        saved = save_profile(plugin, {"interests": [{"topic": "木工"}]}, source="manual")
        self.assertEqual(saved["source"], "manual")
        self.assertTrue(saved["generated_at"])
        self.assertEqual(load_profile(plugin)["interests"][0]["topic"], "木工")

    def test_保存会覆盖旧内容(self):
        plugin = _FakePlugin()
        save_profile(plugin, {"interests": [{"topic": "旧的"}]})
        save_profile(plugin, {"interests": [{"topic": "新的"}]})
        topics = [item["topic"] for item in load_profile(plugin)["interests"]]
        self.assertEqual(topics, ["新的"])


class SummarizeTests(unittest.IsolatedAsyncioTestCase):
    GOOD = json.dumps({
        "interests": [{"topic": "独立游戏", "type": "theme", "weight": 0.8, "evidence": "设定里提到打游戏"}],
        "dislikes": [{"topic": "标题党", "type": "other", "weight": 0.7, "evidence": "她讨厌浮夸"}],
        "explore_seeds": ["木工"],
    }, ensure_ascii=False)

    async def test_从人设总结出画像(self):
        plugin = _PersonaPlugin(reply=f"Thinking Process: 我先想一下\n{self.GOOD}")
        profile = await summarize_from_persona(plugin)
        self.assertEqual(profile["source"], "persona")
        self.assertEqual(profile["interests"][0]["topic"], "独立游戏")
        self.assertEqual(profile["explore_seeds"], ["木工"])

    async def test_总结不落盘(self):
        plugin = _PersonaPlugin(reply=self.GOOD)
        await summarize_from_persona(plugin)
        self.assertNotIn(TASTE_PROFILE_FILE, plugin.store, "总结只返回候选，不该写文件")

    async def test_请求里带上人设原文(self):
        plugin = _PersonaPlugin(persona="她喜欢深海", reply=self.GOOD)
        await summarize_from_persona(plugin)
        prompt, kwargs = plugin.calls[0]
        self.assertIn("她喜欢深海", prompt)
        self.assertEqual(kwargs.get("max_tokens"), 1200)

    async def test_人设为空时报错(self):
        plugin = _PersonaPlugin(persona="   ", reply=self.GOOD)
        with self.assertRaises(TasteProfileError):
            await summarize_from_persona(plugin)

    async def test_模型返回空时报错(self):
        plugin = _PersonaPlugin(reply="")
        with self.assertRaises(TasteProfileError):
            await summarize_from_persona(plugin)

    async def test_返回非JSON时报错(self):
        plugin = _PersonaPlugin(reply="我觉得她会喜欢游戏")
        with self.assertRaises(TasteProfileError):
            await summarize_from_persona(plugin)

    async def test_没有兴趣条目时报错(self):
        plugin = _PersonaPlugin(reply=json.dumps({"interests": []}))
        with self.assertRaises(TasteProfileError):
            await summarize_from_persona(plugin)

    def test_提示词要求每条都给依据(self):
        prompt = summarize_prompt("她喜欢深海")
        self.assertIn("evidence", prompt)
        self.assertIn("不要因为", prompt)


if __name__ == "__main__":
    unittest.main()
