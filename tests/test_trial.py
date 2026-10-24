"""试运行（干跑）的离线测试。

重点守两件事：**不碰写接口**、**不把内部字段漏给前端**。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.trial import MAX_CANDIDATES, run_trial  # noqa: E402


def _video(index: int) -> dict:
    return {
        "bvid": f"BV{index}",
        "title": f"视频 {index}",
        "up_name": f"UP{index}",
        "play": 1000 * index,
        "duration": 300,
        "tname": "科技",
        "_source": "pool",
        "pic": "https://i0.hdslb.com/x.jpg",
        # 内部字段，不该出现在试运行结果里
        "_evaluation_diagnostic": {"secret": True},
        "_exploration": True,
    }


class _FakePlugin:
    def __init__(self, cookie=(True, "✅ 测试号 (UID:1) LV2"), videos=None, pool_raises=None):
        self.config = {
            "ENABLE_PROACTIVE": True,
            "PROACTIVE_LIKE_MIN_SCORE": 6,
            "PROACTIVE_COIN_MIN_SCORE": 8,
        }
        self._cookie = cookie
        self._videos = videos if videos is not None else [_video(i) for i in range(1, 4)]
        self._pool_raises = pool_raises
        self.write_calls = []

    async def check_cookie(self):
        return self._cookie

    async def _get_pool_videos(self, *args, **kwargs):
        if self._pool_raises:
            raise self._pool_raises
        return self._videos


class TrialTests(unittest.IsolatedAsyncioTestCase):
    async def test_正常返回结构(self):
        out = await run_trial(_FakePlugin())
        for key in ("ok", "cookie", "candidates", "candidate_total", "plan", "errors", "elapsed_ms"):
            self.assertIn(key, out)
        self.assertTrue(out["ok"])
        self.assertTrue(out["cookie"]["ok"])
        self.assertEqual(out["candidate_total"], 3)
        self.assertEqual(len(out["candidates"]), 3)

    async def test_候选字段被裁剪且不漏内部字段(self):
        out = await run_trial(_FakePlugin())
        first = out["candidates"][0]
        self.assertEqual(
            set(first),
            {"bvid", "title", "up_name", "play", "duration", "tname", "source", "pic"},
        )
        dumped = repr(out["candidates"])
        self.assertNotIn("_evaluation_diagnostic", dumped)
        self.assertNotIn("_exploration", dumped)
        self.assertEqual(first["source"], "pool")

    async def test_候选数量有上限(self):
        videos = [_video(i) for i in range(1, 20)]
        out = await run_trial(_FakePlugin(videos=videos))
        self.assertEqual(out["candidate_total"], 19)
        self.assertEqual(len(out["candidates"]), MAX_CANDIDATES)

    async def test_取片失败只记错误不抛(self):
        out = await run_trial(_FakePlugin(pool_raises=RuntimeError("网络炸了")))
        self.assertFalse(out["ok"])
        self.assertTrue(any("取片失败" in e for e in out["errors"]))
        self.assertEqual(out["candidates"], [])

    async def test_cookie失败不影响取片(self):
        out = await run_trial(_FakePlugin(cookie=(False, "❌ Cookie 已失效")))
        self.assertFalse(out["cookie"]["ok"])
        self.assertTrue(out["ok"], "cookie 失败不算试运行失败，取片仍应继续")
        self.assertEqual(len(out["candidates"]), 3)

    async def test_计划反映配置阈值(self):
        out = await run_trial(_FakePlugin())
        plan = out["plan"]
        self.assertTrue(plan["proactive_enabled"])
        by_action = {item["action"]: item for item in plan["actions"]}
        self.assertEqual(by_action["点赞"]["threshold"], 6)
        self.assertEqual(by_action["投币"]["threshold"], 8)
        self.assertIn("不会执行任何写操作", plan["note"])

    async def test_总开关关闭时计划里能看出来(self):
        plugin = _FakePlugin()
        plugin.config["ENABLE_PROACTIVE"] = False
        out = await run_trial(plugin)
        self.assertFalse(out["plan"]["proactive_enabled"])

    async def test_不调用任何写操作(self):
        plugin = _FakePlugin()
        await run_trial(plugin)
        self.assertEqual(plugin.write_calls, [], "试运行不该触发写操作")


if __name__ == "__main__":
    unittest.main()
