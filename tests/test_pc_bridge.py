"""陪伴联动的纯离线测试（不联网、不需要真的装陪伴插件）。"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.pc_bridge import (  # noqa: E402
    PC_API_VERSION,
    compose_with_persona,
    deliver_via_pc,
    find_pc_api,
    share_via_pc,
    user_id_from_umo,
)


class _FakeApi:
    api_version = PC_API_VERSION

    def __init__(self, text="她的一句话", send_ok=True, gen_raises=None, send_raises=None):
        self._text = text
        self._send_ok = send_ok
        self._gen_raises = gen_raises
        self._send_raises = send_raises
        self.sent = []
        self.recorded = []

    async def generate_reality_touch_text(self, prompt):
        if self._gen_raises:
            raise self._gen_raises
        return self._text

    async def send_reality_touch_chat(self, umo, text):
        if self._send_raises:
            raise self._send_raises
        self.sent.append((umo, text))
        return self._send_ok

    async def record_reality_touch_output(self, user_id, text):
        self.recorded.append((user_id, text))


class _Star:
    def __init__(self, name, api):
        self.name = name
        self.star_cls = type("X", (), {"extension_api": api})()


class _Ctx:
    def __init__(self, stars, raises=False):
        self._stars = stars
        self._raises = raises

    def get_all_stars(self):
        if self._raises:
            raise RuntimeError("枚举失败")
        return self._stars


class FindApiTests(unittest.TestCase):
    def test_找到正确插件(self):
        api = _FakeApi()
        ctx = _Ctx([_Star("别的插件", None), _Star("astrbot_plugin_private_companion", api)])
        self.assertIs(find_pc_api(ctx), api)

    def test_版本不符不认(self):
        api = _FakeApi()
        api.api_version = "companion.product.v0"
        ctx = _Ctx([_Star("astrbot_plugin_private_companion", api)])
        self.assertIsNone(find_pc_api(ctx))

    def test_没有门面返回None(self):
        ctx = _Ctx([_Star("astrbot_plugin_private_companion", None)])
        self.assertIsNone(find_pc_api(ctx))

    def test_枚举抛错返回None(self):
        self.assertIsNone(find_pc_api(_Ctx([], raises=True)))


class UserIdTests(unittest.TestCase):
    def test_标准umo(self):
        self.assertEqual(
            user_id_from_umo("aiocqhttp:FriendMessage:3698737403"), "3698737403"
        )

    def test_空或残缺(self):
        for value in ("", "aiocqhttp:FriendMessage", None):
            self.assertEqual(user_id_from_umo(value), "")


class ComposeTests(unittest.IsolatedAsyncioTestCase):
    async def test_正常生成(self):
        self.assertEqual(await compose_with_persona(_FakeApi("一句"), "p"), "一句")

    async def test_空文本返回None(self):
        self.assertIsNone(await compose_with_persona(_FakeApi("   "), "p"))

    async def test_抛错返回None(self):
        api = _FakeApi(gen_raises=RuntimeError("模型挂了"))
        self.assertIsNone(await compose_with_persona(api, "p"))

    async def test_超时返回None(self):
        class _Slow(_FakeApi):
            async def generate_reality_touch_text(self, prompt):
                await asyncio.sleep(5)
                return "太晚了"

        with patch("core.pc_bridge.GENERATE_TIMEOUT", 0.01):
            self.assertIsNone(await compose_with_persona(_Slow(), "p"))

    async def test_没有该方法返回None(self):
        class _NoGen:
            pass

        self.assertIsNone(await compose_with_persona(_NoGen(), "p"))


class DeliverTests(unittest.IsolatedAsyncioTestCase):
    async def test_成功发送并记录(self):
        api = _FakeApi()
        self.assertTrue(await deliver_via_pc(api, "aiocqhttp:FriendMessage:123", "正文"))
        self.assertEqual(api.sent, [("aiocqhttp:FriendMessage:123", "正文")])
        self.assertEqual(api.recorded, [("123", "正文")])

    async def test_发送返回False时不算成功(self):
        api = _FakeApi(send_ok=False)
        self.assertFalse(await deliver_via_pc(api, "aiocqhttp:FriendMessage:1", "正文"))
        self.assertEqual(api.recorded, [], "没发出去就不该记录")

    async def test_发送抛错返回False(self):
        api = _FakeApi(send_raises=RuntimeError("通道挂了"))
        self.assertFalse(await deliver_via_pc(api, "aiocqhttp:FriendMessage:1", "正文"))

    async def test_记录抛错不影响已发出(self):
        class _BadRecord(_FakeApi):
            async def record_reality_touch_output(self, user_id, text):
                raise RuntimeError("记录失败")

        api = _BadRecord()
        self.assertTrue(await deliver_via_pc(api, "aiocqhttp:FriendMessage:1", "正文"))

    async def test_空umo或空文本直接False(self):
        api = _FakeApi()
        self.assertFalse(await deliver_via_pc(api, "", "正文"))
        self.assertFalse(await deliver_via_pc(api, "aiocqhttp:FriendMessage:1", ""))


class ShareTests(unittest.IsolatedAsyncioTestCase):
    async def test_没有陪伴时回退(self):
        ok, text = await share_via_pc(_Ctx([]), "umo", "prompt", "兜底文案")
        self.assertFalse(ok)
        self.assertEqual(text, "兜底文案")

    async def test_有陪伴时用她的人格(self):
        api = _FakeApi("她的原话")
        ctx = _Ctx([_Star("astrbot_plugin_private_companion", api)])
        ok, text = await share_via_pc(ctx, "aiocqhttp:FriendMessage:1", "prompt", "兜底")
        self.assertTrue(ok)
        self.assertEqual(text, "她的原话")
        self.assertEqual(api.sent[0][1], "她的原话")

    async def test_生成失败退回兜底文案但仍走她的通道(self):
        api = _FakeApi(gen_raises=RuntimeError("模型挂了"))
        ctx = _Ctx([_Star("astrbot_plugin_private_companion", api)])
        ok, text = await share_via_pc(ctx, "aiocqhttp:FriendMessage:1", "prompt", "兜底")
        self.assertTrue(ok)
        self.assertEqual(text, "兜底")
        self.assertEqual(api.sent[0][1], "兜底")

    async def test_她的通道失败时交回调用方(self):
        api = _FakeApi(send_ok=False)
        ctx = _Ctx([_Star("astrbot_plugin_private_companion", api)])
        ok, _text = await share_via_pc(ctx, "aiocqhttp:FriendMessage:1", "prompt", "兜底")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
