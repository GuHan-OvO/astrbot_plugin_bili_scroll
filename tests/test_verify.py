"""评论复核的纯离线测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.verify import (  # noqa: E402
    STATE_ERROR,
    STATE_HIDDEN,
    STATE_MISSING,
    STATE_VISIBLE,
    check_comment,
    parse_reply_state,
    schedule_verify,
    verify_later,
)


def _payload(replies, code=0):
    return {"code": code, "data": {"replies": replies}}


class _FakePlugin:
    def __init__(self, payload=None, exc=None):
        self.payload = payload
        self.exc = exc
        self.appended = []
        self.calls = []

    async def _http_get(self, url, params=None):
        self.calls.append((url, params))
        if self.exc:
            raise self.exc
        return self.payload, ""

    def _append_json_list(self, path, item, cap=None):
        self.appended.append((str(path), item, cap))


class ParseStateTests(unittest.TestCase):
    def test_正常可见(self):
        self.assertEqual(parse_reply_state(_payload([{"rpid": 1, "state": 0}]), 1), STATE_VISIBLE)

    def test_被折叠(self):
        self.assertEqual(parse_reply_state(_payload([{"rpid": 1, "state": 1}]), 1), STATE_HIDDEN)

    def test_rpid类型不一致也能匹配(self):
        self.assertEqual(
            parse_reply_state(_payload([{"rpid": "123", "state": 0}]), 123), STATE_VISIBLE
        )

    def test_找不到(self):
        self.assertEqual(parse_reply_state(_payload([{"rpid": 2, "state": 0}]), 1), STATE_MISSING)

    def test_列表为空也算找不到(self):
        self.assertEqual(parse_reply_state(_payload([]), 1), STATE_MISSING)

    def test_接口报错(self):
        self.assertEqual(parse_reply_state({"code": -412, "message": "风控"}, 1), STATE_ERROR)

    def test_结构异常(self):
        for bad in (None, "x", {}, {"code": 0, "data": None}, {"code": 0, "data": {"replies": "x"}}):
            self.assertEqual(parse_reply_state(bad, 1), STATE_ERROR)

    def test_列表里有脏项也跳过(self):
        payload = _payload([None, "x", {"rpid": 1, "state": 0}])
        self.assertEqual(parse_reply_state(payload, 1), STATE_VISIBLE)


class CheckCommentTests(unittest.IsolatedAsyncioTestCase):
    async def test_请求参数正确(self):
        plugin = _FakePlugin(_payload([{"rpid": 7, "state": 0}]))
        state = await check_comment(plugin, 999, 7)
        self.assertEqual(state, STATE_VISIBLE)
        url, params = plugin.calls[0]
        self.assertIn("/x/v2/reply", url)
        self.assertEqual(params["oid"], 999)
        self.assertEqual(params["sort"], 0, "要按时间倒序，否则新评论不在第一页")

    async def test_page_size被夹到20以内(self):
        plugin = _FakePlugin(_payload([]))
        await check_comment(plugin, 1, 1, page_size=999)
        self.assertEqual(plugin.calls[0][1]["ps"], 20)
        await check_comment(plugin, 1, 1, page_size=0)
        self.assertEqual(plugin.calls[1][1]["ps"], 1)

    async def test_网络异常归到error(self):
        plugin = _FakePlugin(exc=RuntimeError("超时"))
        self.assertEqual(await check_comment(plugin, 1, 1), STATE_ERROR)


class VerifyLaterTests(unittest.IsolatedAsyncioTestCase):
    async def test_可见时记一条并通过(self):
        plugin = _FakePlugin(_payload([{"rpid": 5, "state": 0}]))
        state = await verify_later(plugin, 42, 5, delay=0)
        self.assertEqual(state, STATE_VISIBLE)
        self.assertEqual(len(plugin.appended), 1)
        _path, entry, cap = plugin.appended[0]
        self.assertEqual(entry["state"], STATE_VISIBLE)
        self.assertEqual(entry["rpid"], 5)
        self.assertEqual(entry["oid"], 42)
        self.assertIn("time", entry)
        self.assertTrue(cap)

    async def test_未找到也会记账(self):
        plugin = _FakePlugin(_payload([]))
        state = await verify_later(plugin, 42, 5, delay=0)
        self.assertEqual(state, STATE_MISSING)
        self.assertEqual(plugin.appended[0][1]["state"], STATE_MISSING)

    async def test_记账失败不影响返回值(self):
        class _BadRecord(_FakePlugin):
            def _append_json_list(self, *args, **kwargs):
                raise RuntimeError("磁盘满")

        plugin = _BadRecord(_payload([{"rpid": 5, "state": 0}]))
        self.assertEqual(await verify_later(plugin, 42, 5, delay=0), STATE_VISIBLE)


class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_有事件循环时排进后台(self):
        plugin = _FakePlugin(_payload([{"rpid": 5, "state": 0}]))
        scheduled = schedule_verify(plugin, 42, 5, delay=0)
        self.assertTrue(scheduled)
        await __import__("asyncio").sleep(0.05)  # 让后台任务跑完
        self.assertEqual(len(plugin.appended), 1)

    async def test_没有rpid直接跳过(self):
        plugin = _FakePlugin(_payload([]))
        self.assertFalse(schedule_verify(plugin, 42, 0))
        await __import__("asyncio").sleep(0.01)
        self.assertEqual(plugin.calls, [])


if __name__ == "__main__":
    unittest.main()
