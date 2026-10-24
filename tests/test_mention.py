"""真 @ 映射构造的单元测试（纯离线，不发任何请求）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.mention import (  # noqa: E402
    build_mention_map,
    compose_comment,
    resolve_mention_map,
    resolve_owner_mid,
)


class BuildMentionMapTests(unittest.TestCase):
    def test_正常配置直接成映射(self):
        self.assertEqual(build_mention_map("孤寒钴含咕_", 1215576595), {"孤寒钴含咕_": 1215576595})

    def test_字符串里的空格与前置at会被清掉(self):
        self.assertEqual(build_mention_map("  @孤寒钴含咕_  ", " 1215576595 "), {"孤寒钴含咕_": 1215576595})

    def test_缺昵称返回空(self):
        for name in ("", "   ", "@", None):
            self.assertEqual(build_mention_map(name, 1215576595), {})

    def test_缺uid返回空(self):
        for mid in ("", None, "abc", 0, -1):
            self.assertEqual(build_mention_map("某用户", mid), {})

    def test_昵称过长返回空(self):
        self.assertEqual(build_mention_map("a" * 33, 123), {})

    def test_uid超过上界返回空(self):
        self.assertEqual(build_mention_map("某用户", 2**63), {})


class ComposeCommentTests(unittest.TestCase):
    def test_普通正文加前缀(self):
        self.assertEqual(compose_comment("这期讲得清楚", "某用户"), "@某用户 这期讲得清楚")

    def test_正文已含at时不重复(self):
        self.assertEqual(
            compose_comment("@某用户 这期讲得清楚", "某用户"),
            "@某用户 这期讲得清楚",
        )

    def test_正文多个at时全部收成一个(self):
        self.assertEqual(
            compose_comment("@某用户 开头 @某用户 结尾", "某用户"),
            "@某用户 开头 结尾",
        )

    def test_at出现在词中不会被误删(self):
        # @某用户A 与 @某用户 是两个不同的提及，不能把前者一起吃掉
        self.assertEqual(
            compose_comment("@某用户A 你好", "某用户"),
            "@某用户 @某用户A 你好",
        )

    def test_空正文只留at(self):
        self.assertEqual(compose_comment("   ", "某用户"), "@某用户")

    def test_昵称空时原样返回(self):
        self.assertEqual(compose_comment("正文", ""), "正文")

    def test_昵称含正则特殊字符(self):
        self.assertEqual(compose_comment("@a.b(c) 你好", "a.b(c)"), "@a.b(c) 你好")


class ResolveOwnerMidTests(unittest.IsolatedAsyncioTestCase):
    async def test_精确匹配命中(self):
        async def search(keyword, ps):
            return [
                {"mid": 111, "uname": "别的名字"},
                {"mid": 222, "uname": "目标"},
            ]

        self.assertEqual(await resolve_owner_mid("目标", search), 222)

    async def test_没有精确匹配就不猜(self):
        async def search(keyword, ps):
            return [{"mid": 111, "uname": "目标的小号"}]

        self.assertIsNone(await resolve_owner_mid("目标", search))

    async def test_搜索抛错返回None(self):
        async def search(keyword, ps):
            raise RuntimeError("网络炸了")

        self.assertIsNone(await resolve_owner_mid("目标", search))

    async def test_结果里有脏数据也能跳过(self):
        async def search(keyword, ps):
            return [None, "x", {"mid": "bad", "uname": "目标"}, {"mid": 333, "uname": "目标"}]

        self.assertEqual(await resolve_owner_mid("目标", search), 333)

    async def test_没有search实现时返回None(self):
        self.assertIsNone(await resolve_owner_mid("目标", None))


class ResolveMentionMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_配置齐全时不发搜索(self):
        calls = []

        async def search(keyword, ps):
            calls.append(keyword)
            return []

        mapping = await resolve_mention_map("某用户", 999, search)
        self.assertEqual(mapping, {"某用户": 999})
        self.assertEqual(calls, [])

    async def test_缺uid时才搜索(self):
        async def search(keyword, ps):
            return [{"mid": 888, "uname": "某用户"}]

        self.assertEqual(await resolve_mention_map("某用户", 0, search), {"某用户": 888})

    async def test_搜不到返回空字典(self):
        async def search(keyword, ps):
            return []

        self.assertEqual(await resolve_mention_map("某用户", None, search), {})

    async def test_昵称为空直接空字典(self):
        self.assertEqual(await resolve_mention_map("", 999, None), {})


if __name__ == "__main__":
    unittest.main()


class SendCommentMentionTests(unittest.IsolatedAsyncioTestCase):
    """_send_comment 的请求体契约（用假 self，不联网）。"""

    class _Fake:
        def __init__(self, code=0):
            self.config = {"BILI_JCT": "csrf-token"}
            self.sent = []
            self._code = code

        async def _http_post(self, url, data=None):
            self.sent.append(data)
            return {"code": self._code, "message": "stub"}, {}

    async def test_带映射时请求体含at字段与plat(self):
        from core.bilibili import BilibiliAPIMixin

        fake = self._Fake()
        ok = await BilibiliAPIMixin._send_comment(
            fake, 123, "@某人 正文", at_name_to_mid={"某人": 456}
        )
        self.assertTrue(ok)
        body = fake.sent[0]
        self.assertEqual(body["at_name_to_mid"], '{"某人": 456}')
        self.assertEqual(body["plat"], 1)
        self.assertEqual(body["csrf"], "csrf-token")
        self.assertEqual(body["oid"], 123)

    async def test_不带映射时不加这两个字段(self):
        from core.bilibili import BilibiliAPIMixin

        fake = self._Fake()
        ok = await BilibiliAPIMixin._send_comment(fake, 123, "正文")
        self.assertTrue(ok)
        body = fake.sent[0]
        self.assertNotIn("at_name_to_mid", body)
        self.assertNotIn("plat", body)

    async def test_带映射失败时不做纯文本重发(self):
        from core.bilibili import BilibiliAPIMixin

        fake = self._Fake(code=12025)
        ok = await BilibiliAPIMixin._send_comment(
            fake, 123, "正文", at_name_to_mid={"某人": 456}
        )
        self.assertFalse(ok)
        self.assertEqual(len(fake.sent), 1, "失败后不该再发一条纯文本评论")
