"""试运行（干跑）的离线测试。

重点守两件事：**不碰写接口**、**不把内部字段漏给前端**。
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.trial import (
    LIVE_COOLDOWN_SECONDS,
    MAX_CANDIDATES,
    TEST_COOLDOWN_SECONDS,
    run_test_action,
    send_test_mention,
    send_test_private,
    _state,
    live_status,
    run_trial,
    start_live,
)  # noqa: E402


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


class LiveTrialTests(unittest.IsolatedAsyncioTestCase):
    """真跑一条：后台启动 + 轮询状态。"""

    def _plugin(self, run=None, rows=None):
        plugin = _FakePlugin()
        plugin._watch_rows = list(rows or [])

        async def _run_proactive(max_watch=None):
            plugin._run_args = max_watch
            if run:
                await run(plugin)

        plugin._run_proactive = _run_proactive

        def _load_json(path, default):
            return list(plugin._watch_rows)

        plugin._load_json = _load_json
        return plugin

    async def test_启动后running为真并跑完置假(self):
        async def run(plugin):
            plugin._watch_rows.append(
                {"bvid": "BV1", "title": "看过的视频", "score": 8.5, "actions": ["👍点赞"]}
            )

        plugin = self._plugin(run=run)
        started = start_live(plugin)
        self.assertTrue(started["started"])
        await asyncio.sleep(0.05)
        state = live_status(plugin)
        self.assertFalse(state["running"])
        self.assertEqual(state["watched"]["bvid"], "BV1")
        self.assertEqual(state["watched"]["score"], 8.5)
        self.assertEqual(state["watched"]["actions"], ["👍点赞"])
        self.assertEqual(plugin._run_args, 1, "只应该刷一个视频")

    async def test_重复启动被拒(self):
        async def run(plugin):
            await asyncio.sleep(0.1)

        plugin = self._plugin(run=run)
        self.assertTrue(start_live(plugin)["started"])
        second = start_live(plugin)
        self.assertFalse(second["started"])
        self.assertIn("还没跑完", second["reason"])
        await asyncio.sleep(0.15)

    async def test_没看成任何视频时watched为空(self):
        plugin = self._plugin(run=None)
        start_live(plugin)
        await asyncio.sleep(0.05)
        state = live_status(plugin)
        self.assertFalse(state["running"])
        self.assertIsNone(state["watched"])

    async def test_跑挂了也把状态收尾(self):
        async def run(plugin):
            raise RuntimeError("炸了")

        plugin = self._plugin(run=run)
        start_live(plugin)
        await asyncio.sleep(0.05)
        state = live_status(plugin)
        self.assertFalse(state["running"], "异常也要把 running 复位，否则按钮永远转")
        self.assertIn("炸了", state["error"])

    async def test_只取新增的那条(self):
        async def run(plugin):
            plugin._watch_rows.append({"bvid": "BV2", "title": "新的", "score": 7})

        plugin = self._plugin(run=run, rows=[{"bvid": "BV0", "title": "旧的"}])
        start_live(plugin)
        await asyncio.sleep(0.05)
        self.assertEqual(live_status(plugin)["watched"]["bvid"], "BV2")

    async def test_跑完后进入冷却且再点被拒(self):
        plugin = self._plugin(run=None)
        start_live(plugin)
        await asyncio.sleep(0.05)
        state = live_status(plugin)
        self.assertFalse(state["running"])
        self.assertGreater(state["cooldown_remaining"], 0, "刚跑完应该还在冷却")

        second = start_live(plugin)
        self.assertFalse(second["started"])
        self.assertIn("冷却", second["reason"])
        self.assertGreater(second["retry_after"], 0)

    async def test_冷却结束后可以再刷(self):
        plugin = self._plugin(run=None)
        start_live(plugin)
        await asyncio.sleep(0.05)
        # 把完成时间往前推，模拟冷却已过
        _state(plugin)["finished_at"] -= LIVE_COOLDOWN_SECONDS + 1
        self.assertEqual(live_status(plugin)["cooldown_remaining"], 0)
        self.assertTrue(start_live(plugin)["started"])
        await asyncio.sleep(0.05)

    async def test_冷却常量是正数且不太短(self):
        self.assertGreaterEqual(LIVE_COOLDOWN_SECONDS, 20, "太短挡不住连点")


class TrialTestActionTests(unittest.IsolatedAsyncioTestCase):
    """单独测私信 / 真 @。"""

    def _plugin(self, *, rows=None, oid=12345, private_ok=True, comment_result=999):
        plugin = _FakePlugin()
        plugin._watch_rows = list(rows or [])
        plugin.config.update({"OWNER_MID": "10001", "OWNER_BILI_NAME": "主人"})
        plugin.private_calls = []
        plugin.comment_calls = []

        def _load_json(path, default):
            return list(plugin._watch_rows)

        async def _send_private(mid, text):
            plugin.private_calls.append((mid, text))
            return private_ok

        async def _get_oid(bvid):
            plugin.oid_bvid = bvid
            return oid

        async def _send_comment(o, text, oid_type=1, at_name_to_mid=None):
            plugin.comment_calls.append({"oid": o, "text": text, "at": at_name_to_mid})
            return comment_result

        plugin._load_json = _load_json
        plugin._send_bili_private_message = _send_private
        plugin._get_video_oid = _get_oid
        plugin._send_comment = _send_comment
        return plugin

    async def test_私信成功(self):
        plugin = self._plugin()
        out = await send_test_private(plugin)
        self.assertTrue(out["ok"])
        self.assertEqual(out["target_mid"], "10001")
        self.assertEqual(len(plugin.private_calls), 1)
        self.assertEqual(plugin.private_calls[0][0], 10001)

    async def test_私信缺UID直接报错不发送(self):
        plugin = self._plugin()
        plugin.config["OWNER_MID"] = ""
        out = await send_test_private(plugin)
        self.assertFalse(out["ok"])
        self.assertIn("OWNER_MID", out["error"])
        self.assertEqual(plugin.private_calls, [])

    async def test_私信失败带提示(self):
        plugin = self._plugin(private_ok=False)
        out = await send_test_private(plugin)
        self.assertFalse(out["ok"])
        self.assertIn("Cookie", out["detail"])

    async def test_提及带上真at映射(self):
        plugin = self._plugin(rows=[{"bvid": "BV1", "title": "x"}])
        out = await send_test_mention(plugin)
        self.assertTrue(out["ok"])
        self.assertEqual(out["bvid"], "BV1")
        self.assertEqual(out["oid"], 12345)
        self.assertIn("10001", str(out["at_map"]), "OWNER_MID 应该进映射")
        call = plugin.comment_calls[0]
        self.assertEqual(call["oid"], 12345)
        self.assertTrue(call["at"], "必须带 at_name_to_mid，否则只是纯文本 @")
        self.assertIn("@", call["text"])

    async def test_提及没有看过视频时拒绝(self):
        plugin = self._plugin(rows=[])
        out = await send_test_mention(plugin)
        self.assertFalse(out["ok"])
        self.assertIn("先刷一轮", out["error"])
        self.assertEqual(plugin.comment_calls, [])

    async def test_测完进入冷却(self):
        plugin = self._plugin()
        self.assertTrue((await run_test_action(plugin, "private"))["ok"])
        second = await run_test_action(plugin, "private")
        self.assertFalse(second["ok"])
        self.assertIn("冷却", second["error"])
        self.assertGreater(second["retry_after"], 0)
        self.assertEqual(len(plugin.private_calls), 1, "冷却期不该真的再发")

    async def test_未知类型不给猜(self):
        plugin = self._plugin()
        out = await run_test_action(plugin, "whatever")
        self.assertFalse(out["ok"])
        self.assertIn("未知的测试类型", out["error"])

    async def test_测试冷却常量有值(self):
        self.assertGreaterEqual(TEST_COOLDOWN_SECONDS, 10)


if __name__ == "__main__":
    unittest.main()
