"""评论复核的纯离线测试。

所有网络响应都是构造的 payload，不发起任何真实请求。
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

import core.verify as verify  # noqa: E402
from core.verify import (  # noqa: E402
    STATE_DELETED,
    STATE_FOLDED,
    STATE_INVISIBLE,
    STATE_PENDING,
    STATE_SELF_ONLY,
    STATE_UNVERIFIED,
    STATE_VISIBLE,
    build_view_headers,
    check_visibility,
    classify_item,
    find_reply,
    schedule_verify,
    verify_enabled,
    verify_later,
)


def _item(rpid=7, state=0, attr=0, invisible=False, folded=False):
    return {
        "rpid": rpid,
        "state": state,
        "attr": attr,
        "invisible": invisible,
        "folder": {"is_folded": folded, "has_folded": False},
    }


def _payload(replies=None, *, code=0, top=None, hots=None, top_replies=None, cursor=None):
    data = {"replies": list(replies or [])}
    if top is not None:
        data["top"] = top
    if hots is not None:
        data["hots"] = hots
    if top_replies is not None:
        data["top_replies"] = top_replies
    if cursor is not None:
        data["cursor"] = cursor
    return {"code": code, "data": data}


class _FakePlugin:
    """按视角返回不同 payload；reply/reply 单独一份。"""

    def __init__(self, *, anon=None, auth=None, anon_seq=None, sub=None, config=None, exc=None):
        self.queues = {
            "anon": list(anon_seq) if anon_seq else [anon if anon is not None else _payload()],
            "auth": [auth if auth is not None else _payload()],
        }
        self.sub = sub if sub is not None else {"code": 0, "data": {"replies": []}}
        self.config = dict(config or {})
        self.exc = exc
        self.calls = []
        self.appended = []

    def _headers(self):
        return {
            "Cookie": "SESSDATA=sess; bili_jct=jct; DedeUserID=42; buvid3=b3; buvid4=b4",
            "User-Agent": "ua",
        }

    async def sign_wbi_params(self, params):
        out = dict(params)
        out["w_rid"] = "stub"
        return out

    def _take(self, bucket):
        queue = self.queues[bucket]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def _http_get(self, url, headers=None, params=None, **kwargs):
        self.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )
        if self.exc:
            raise self.exc
        if "reply/reply" in url:
            return self.sub, None
        cookie = str((headers or {}).get("Cookie", ""))
        return self._take("auth" if "SESSDATA" in cookie else "anon"), None

    def _append_json_list(self, path, item, cap=None):
        self.appended.append((str(path), item, cap))


class _BaseCase(unittest.TestCase):
    def setUp(self):
        verify._last_oid_check.clear()
        verify._inflight = 0
        self._interval = verify.VERIFY_OID_MIN_INTERVAL
        verify.VERIFY_OID_MIN_INTERVAL = 0

    def tearDown(self):
        verify.VERIFY_OID_MIN_INTERVAL = self._interval
        verify._last_oid_check.clear()
        verify._inflight = 0


class ClassifyTests(unittest.TestCase):
    def test_state0是可见(self):
        self.assertEqual(classify_item(_item()), STATE_VISIBLE)

    def test_state17是仅自己可见(self):
        self.assertEqual(classify_item(_item(state=17)), STATE_SELF_ONLY)

    def test_折叠(self):
        self.assertEqual(classify_item(_item(folded=True)), STATE_FOLDED)

    def test_invisible(self):
        self.assertEqual(classify_item(_item(invisible=True)), STATE_INVISIBLE)

    def test_未知state不硬判(self):
        self.assertEqual(classify_item(_item(state=5)), STATE_UNVERIFIED)

    def test_attr位只能当信号(self):
        self.assertEqual(classify_item(_item(state=1, attr=1 << 17)), STATE_SELF_ONLY)

    def test_脏条目(self):
        for bad in (None, "x", []):
            self.assertEqual(classify_item(bad), STATE_UNVERIFIED)


class FindReplyTests(unittest.TestCase):
    def test_置顶也能找到(self):
        payload = _payload(top={"upper": _item(rpid=9)})
        item, bucket = find_reply(payload, 9)
        self.assertEqual(item["rpid"], 9)
        self.assertEqual(bucket, "top.upper")

    def test_热评也能找到(self):
        item, bucket = find_reply(_payload(hots=[_item(rpid=11)]), 11)
        self.assertEqual(item["rpid"], 11)
        self.assertEqual(bucket, "hots")

    def test_风控响应不算命中(self):
        self.assertEqual(find_reply({"code": -403, "data": None}, 1), (None, ""))


class CheckVisibilityTests(_BaseCase, unittest.IsolatedAsyncioTestCase):
    async def test_匿名可见(self):
        plugin = _FakePlugin(anon=_payload([_item(7)]))
        result = await check_visibility(plugin, 42, 7)
        self.assertEqual(result["state"], STATE_VISIBLE)
        self.assertEqual(result["view"], "anon")
        self.assertEqual(plugin.calls[0]["params"]["seek_rpid"], "7")
        self.assertEqual(plugin.calls[0]["params"]["mode"], 2)

    async def test_匿名查不到但登录可见判仅自己可见(self):
        plugin = _FakePlugin(anon=_payload(), auth=_payload([_item(7)]))
        result = await check_visibility(plugin, 42, 7, phase="confirm")
        self.assertEqual(result["state"], STATE_SELF_ONLY)

    async def test_90秒查不到只记pending(self):
        plugin = _FakePlugin(anon=_payload())
        result = await check_visibility(plugin, 42, 7, phase="optimistic")
        self.assertEqual(result["state"], STATE_PENDING)
        self.assertEqual(len(plugin.calls), 1, "乐观阶段只发一次 seek，不翻页也不换视角")

    async def test_两视角都空且12022判删除(self):
        plugin = _FakePlugin(anon=_payload(), auth=_payload(), sub={"code": 12022, "data": None})
        result = await check_visibility(plugin, 42, 7, phase="confirm")
        self.assertEqual(result["state"], STATE_DELETED)

    async def test_探测到存在但列表看不到不判删除(self):
        plugin = _FakePlugin(
            anon=_payload(), auth=_payload(), sub={"code": 0, "data": {"replies": []}}
        )
        result = await check_visibility(plugin, 42, 7, phase="confirm")
        self.assertEqual(result["state"], STATE_UNVERIFIED)

    async def test_风控算unverified且不下结论(self):
        plugin = _FakePlugin(anon={"code": -403, "data": None})
        result = await check_visibility(plugin, 42, 7, phase="confirm")
        self.assertEqual(result["state"], STATE_UNVERIFIED)
        self.assertIn("-403", result["error"])
        self.assertEqual(len(plugin.calls), 1)

    async def test_网络异常算unverified(self):
        plugin = _FakePlugin(exc=TimeoutError("超时"))
        result = await check_visibility(plugin, 42, 7)
        self.assertEqual(result["state"], STATE_UNVERIFIED)

    async def test_seek未命中会翻页(self):
        seek = _payload(cursor={"pagination_reply": {"next_offset": "off1"}})
        page = _payload([_item(7)])
        plugin = _FakePlugin(anon_seq=[seek, page])
        result = await check_visibility(plugin, 42, 7, phase="confirm")
        self.assertEqual(result["state"], STATE_VISIBLE)
        self.assertEqual(len(plugin.calls), 2)

    async def test_type会透传(self):
        plugin = _FakePlugin(anon=_payload([_item(7)]))
        await check_visibility(plugin, 42, 7, type_id=17)
        self.assertEqual(plugin.calls[0]["params"]["type"], 17)

    async def test_翻页不带seek_rpid(self):
        seek = _payload(cursor={"pagination_reply": {"next_offset": "off1"}})
        page = _payload([_item(7)])
        plugin = _FakePlugin(anon_seq=[seek, page])
        result = await check_visibility(plugin, 42, 7, phase="confirm")
        self.assertEqual(result["state"], STATE_VISIBLE)
        second = plugin.calls[1]["params"]
        self.assertNotIn("seek_rpid", second, "翻页必须去掉 seek_rpid，否则永远回到同一页")
        self.assertEqual(second["pagination_str"], '{"offset":"off1"}')

    async def test_回复用父评论当root找人(self):
        sub = {"code": 0, "data": {"replies": [_item(7)]}}
        plugin = _FakePlugin(anon=_payload(), auth=_payload(), sub=sub)
        result = await check_visibility(
            plugin, 42, 7, kind="reply", root_rpid=555, phase="confirm"
        )
        self.assertEqual(result["state"], STATE_SELF_ONLY)
        reply_call = [c for c in plugin.calls if "reply/reply" in c["url"]][0]
        self.assertEqual(reply_call["params"]["root"], "555")

    async def test_关闭匿名视角时只用登录视角(self):
        plugin = _FakePlugin(
            anon=_payload(),
            auth=_payload([_item(7)]),
            config={"COMMENT_VERIFY_ANONYMOUS": False},
        )
        result = await check_visibility(plugin, 42, 7)
        self.assertEqual(result["state"], STATE_VISIBLE)
        self.assertEqual(result["view"], "auth")
        self.assertEqual(len(plugin.calls), 1)


class VerifyLaterTests(_BaseCase, unittest.IsolatedAsyncioTestCase):
    async def test_待确认会在确认时点补判(self):
        plugin = _FakePlugin(anon=_payload(), auth=_payload([_item(7)]))
        state = await verify_later(plugin, 42, 7, delay=0, confirm_delay=0)
        self.assertEqual(state, STATE_SELF_ONLY)
        self.assertEqual(
            [entry[1]["phase"] for entry in plugin.appended], ["optimistic", "confirm"]
        )

    async def test_乐观确认通过就不再查(self):
        plugin = _FakePlugin(anon=_payload([_item(7)]))
        state = await verify_later(plugin, 42, 7, delay=0, confirm_delay=0)
        self.assertEqual(state, STATE_VISIBLE)
        self.assertEqual(len(plugin.appended), 1)

    async def test_记账失败不影响返回值(self):
        class _BadRecord(_FakePlugin):
            def _append_json_list(self, *args, **kwargs):
                raise RuntimeError("磁盘满")

        plugin = _BadRecord(anon=_payload([_item(7)]))
        self.assertEqual(
            await verify_later(plugin, 42, 7, delay=0, confirm_delay=0), STATE_VISIBLE
        )

    def test_关闭开关后不启用(self):
        self.assertFalse(verify_enabled(_FakePlugin(config={"COMMENT_VERIFY_ENABLED": False})))
        self.assertTrue(verify_enabled(_FakePlugin()))


class ScheduleTests(_BaseCase, unittest.IsolatedAsyncioTestCase):
    async def test_排进后台并记账(self):
        plugin = _FakePlugin(anon=_payload([_item(7)]))
        self.assertTrue(schedule_verify(plugin, 42, 7, delay=0))
        await asyncio.sleep(0.05)
        self.assertEqual(len(plugin.appended), 1)

    async def test_没有rpid直接跳过(self):
        plugin = _FakePlugin()
        self.assertFalse(schedule_verify(plugin, 42, 0))
        await asyncio.sleep(0.01)
        self.assertEqual(plugin.calls, [])

    async def test_并发满时跳过(self):
        plugin = _FakePlugin(anon=_payload([_item(7)]), config={"COMMENT_VERIFY_MAX_CONCURRENCY": 1})
        verify._inflight = 1
        self.assertFalse(schedule_verify(plugin, 42, 7, delay=0))


class HeaderTests(unittest.TestCase):
    def test_匿名只保留设备标识(self):
        plugin = _FakePlugin(config={"BUVID3": "b3", "BUVID4": "b4"})
        headers = build_view_headers(plugin, anonymous=True)
        self.assertNotIn("SESSDATA", headers["Cookie"])
        self.assertIn("buvid3=b3", headers["Cookie"])

    def test_登录视角原样返回(self):
        plugin = _FakePlugin()
        self.assertIn("SESSDATA", build_view_headers(plugin, anonymous=False)["Cookie"])


class SendIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_不带at的评论也排复核(self):
        from core.bilibili import BilibiliAPIMixin
        from core.utils import UtilsMixin

        class Bot(UtilsMixin, BilibiliAPIMixin):
            def __init__(self):
                self.config = {"BILI_JCT": "jct"}

            async def _http_post(self, url, headers=None, data=None, **kwargs):
                return {"code": 0, "data": {"rpid": 555}}, None

        bot = Bot()
        with patch("core.bilibili.schedule_verify") as scheduled:
            result = await bot._send_comment(42, "普通评论")
        self.assertEqual(result, 555)
        scheduled.assert_called_once()
        self.assertEqual(scheduled.call_args.kwargs.get("kind"), "comment")
        self.assertFalse(scheduled.call_args.kwargs.get("has_at"))

    async def test_带at的评论标记has_at(self):
        from core.bilibili import BilibiliAPIMixin
        from core.utils import UtilsMixin

        class Bot(UtilsMixin, BilibiliAPIMixin):
            def __init__(self):
                self.config = {"BILI_JCT": "jct"}

            async def _http_post(self, url, headers=None, data=None, **kwargs):
                return {"code": 0, "data": {"rpid": 556}}, None

        bot = Bot()
        with patch("core.bilibili.schedule_verify") as scheduled:
            await bot._send_comment(42, "@主人 看这个", at_name_to_mid={"主人": 1})
        self.assertTrue(scheduled.call_args.kwargs.get("has_at"))

    async def test_回复成功回传rpid并排复核(self):
        from core.bilibili import BilibiliAPIMixin
        from core.utils import UtilsMixin

        class Bot(UtilsMixin, BilibiliAPIMixin):
            def __init__(self):
                self.config = {"BILI_JCT": "jct"}

            async def _http_post(self, url, headers=None, data=None, **kwargs):
                return {"code": 0, "data": {"rpid": 777}}, None

        bot = Bot()
        with patch("core.bilibili.schedule_verify") as scheduled:
            result = await bot._send_reply(42, 100, 1, "回复")
        self.assertEqual(result, 777)
        scheduled.assert_called_once()
        self.assertEqual(scheduled.call_args.kwargs.get("kind"), "reply")

    async def test_发送评论透传type(self):
        from core.bilibili import BilibiliAPIMixin
        from core.utils import UtilsMixin

        class Bot(UtilsMixin, BilibiliAPIMixin):
            def __init__(self):
                self.config = {"BILI_JCT": "jct"}

            async def _http_post(self, url, headers=None, data=None, **kwargs):
                return {"code": 0, "data": {"rpid": 901}}, None

        bot = Bot()
        with patch("core.bilibili.schedule_verify") as scheduled:
            await bot._send_comment(42, "动态评论", oid_type=17)
        self.assertEqual(scheduled.call_args.kwargs.get("type_id"), 17)

    async def test_发送回复透传父评论(self):
        from core.bilibili import BilibiliAPIMixin
        from core.utils import UtilsMixin

        class Bot(UtilsMixin, BilibiliAPIMixin):
            def __init__(self):
                self.config = {"BILI_JCT": "jct"}

            async def _http_post(self, url, headers=None, data=None, **kwargs):
                return {"code": 0, "data": {"rpid": 902}}, None

        bot = Bot()
        with patch("core.bilibili.schedule_verify") as scheduled:
            await bot._send_reply(42, 555, 1, "回复")
        kwargs = scheduled.call_args.kwargs
        self.assertEqual(kwargs.get("kind"), "reply")
        self.assertEqual(kwargs.get("root_rpid"), 555)
        self.assertEqual(kwargs.get("type_id"), 1)

    async def test_发送失败不排复核(self):
        from core.bilibili import BilibiliAPIMixin
        from core.utils import UtilsMixin

        class Bot(UtilsMixin, BilibiliAPIMixin):
            def __init__(self):
                self.config = {"BILI_JCT": "jct"}

            async def _http_post(self, url, headers=None, data=None, **kwargs):
                return {"code": 12025, "message": "敏感词"}, None

        bot = Bot()
        with patch("core.bilibili.schedule_verify") as scheduled:
            result = await bot._send_comment(42, "有敏感词")
        self.assertFalse(result)
        scheduled.assert_not_called()


if __name__ == "__main__":
    unittest.main()
