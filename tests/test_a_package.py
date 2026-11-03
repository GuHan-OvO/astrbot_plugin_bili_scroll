"""A 包回归：下载超时按时长伸缩、工具看片转后台、长日志分条、失败原因入账。

对应上游 chenlu 的 #58 / #60 / #52，以及实例里「actions.detail 只有
handler_returned_unsuccessful，看不出 Cookie/风控/评论区关闭」的补强。
"""
import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from test_write_tools import _install_agent_stubs  # noqa: E402

_install_agent_stubs()

import core.tools as core_tools  # noqa: E402
import core.video as core_video  # noqa: E402
from core.bilibili import BilibiliAPIMixin  # noqa: E402
from core.chat_text import split_for_chat  # noqa: E402
from core.proactive import ProactiveMixin  # noqa: E402
from core.runtime import EventRuntime  # noqa: E402
from core.tools import WATCH_PENDING_MESSAGE  # noqa: E402
from core.tools import create_tools  # noqa: E402
from core.video import VideoMixin  # noqa: E402


class DownloadTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.probe = VideoMixin()

    def test_短视频沿用120秒(self):
        self.assertEqual(self.probe._video_download_timeout(None), 120)
        self.assertEqual(self.probe._video_download_timeout(0), 120)
        self.assertEqual(self.probe._video_download_timeout(200), 120)

    def test_长视频按时长一半放宽(self):
        self.assertEqual(self.probe._video_download_timeout(1200), 600)
        self.assertEqual(self.probe._video_download_timeout(3600), 1800)

    def test_有上限(self):
        self.assertEqual(self.probe._video_download_timeout(100000), 3600)

    def test_非法时长回落到120(self):
        self.assertEqual(self.probe._video_download_timeout("abc"), 120)


class _DownloadProbe(VideoMixin):
    """只实现下载循环需要的最小子集。"""

    def __init__(self, codes):
        self.config = {}
        self.codes = list(codes)
        self.timeouts = []

    def _format_fallbacks(self, max_height):
        return ["f1", "f2", "f3"]

    def _cleanup_partial_downloads(self, bvid, output_dir=None):
        return None

    def _pick_downloaded_video_file(self, bvid, output_dir=None):
        return None

    async def _run_process(self, *args, timeout=None, **kwargs):
        self.timeouts.append(timeout)
        return self.codes.pop(0), "", "boom"


class DownloadTimeoutWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_下载循环用按时长伸缩后的超时(self):
        probe = _DownloadProbe(codes=[1, 1, 1])
        with tempfile.TemporaryDirectory() as tmp, patch.object(core_video, "TEMP_VIDEO_DIR", tmp):
            result = await probe._download_video("BVtest", duration=2400)
        self.assertIsNone(result)
        self.assertEqual(probe.timeouts, [1200, 1200, 1200])

    async def test_长视频超时后不再换格式重下(self):
        probe = _DownloadProbe(codes=[124, 0, 0])
        with tempfile.TemporaryDirectory() as tmp, patch.object(core_video, "TEMP_VIDEO_DIR", tmp):
            result = await probe._download_video("BVtest", duration=2400)
        self.assertIsNone(result)
        # 已经等够久了，换格式只会从头再下一遍
        self.assertEqual(probe.timeouts, [1200])

    async def test_短视频超时仍可换格式(self):
        probe = _DownloadProbe(codes=[124, 1, 1])
        with tempfile.TemporaryDirectory() as tmp, patch.object(core_video, "TEMP_VIDEO_DIR", tmp):
            await probe._download_video("BVtest", duration=60)
        self.assertEqual(probe.timeouts, [120, 120, 120])


class ChatTextTests(unittest.TestCase):
    def test_短文本单条返回(self):
        self.assertEqual(split_for_chat("第一行\n第二行"), ["第一行\n第二行"])

    def test_长文本按行分条且不切行(self):
        lines = [f"第{i}行" + "x" * 40 for i in range(60)]
        chunks = split_for_chat("\n".join(lines), limit=500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 500)
        self.assertEqual("\n".join(chunks), "\n".join(lines))

    def test_单行超长时整行独立成条(self):
        long_line = "y" * 200
        chunks = split_for_chat(f"短行\n{long_line}\n尾行", limit=50)
        self.assertIn(long_line, chunks)

    def test_空文本(self):
        self.assertEqual(split_for_chat(""), [])


class _FakePlugin:
    def __init__(self, behavior):
        self.config = {
            "DEDE_USER_ID": "1",
            "OWNER_MID": "2",
            "OWNER_NAME": "主人",
            "ENABLE_LLM_TOOLS": True,
            "COMMENT_VERIFY_ENABLED": False,
        }
        self.behavior = behavior
        self.watch_calls = []
        self.context = types.SimpleNamespace(send_message=AsyncMock())
        self.event_runtime = types.SimpleNamespace(execute=AsyncMock())

    async def _watch_video_and_save_memory(self, bvid, *, memory_source="", force_rewatch=False):
        self.watch_calls.append(bvid)
        return await self.behavior(bvid)


def _tool(plugin, name):
    return {tool.name: tool for tool in create_tools(plugin)}[name]


def _ctx(event=None):
    return types.SimpleNamespace(context=types.SimpleNamespace(event=event))


class _CapturingChain:
    """替身 MessageChain：把发出去的文本记下来。"""

    def __init__(self, *_args, **_kwargs):
        self.parts = []

    def message(self, text):
        self.parts.append(text)
        return self


class WatchJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_快速看完直接返回结果(self):
        async def behavior(bvid):
            return {"ok": True, "message": f"看完了《{bvid}》", "bvid": bvid}

        plugin = _FakePlugin(behavior)
        tool = _tool(plugin, "watch_video")
        result = await tool.call(_ctx(None), bvid="BV1QZxWerE3F")
        self.assertIn("看完了", result)

    async def test_超时后转后台并回一句话(self):
        release = asyncio.Event()

        async def behavior(bvid):
            await release.wait()
            return {"ok": True, "message": "看完了《长视频》\n（如需互动可调用 bili_action）", "bvid": bvid}

        plugin = _FakePlugin(behavior)
        tool = _tool(plugin, "watch_video")
        event = types.SimpleNamespace(unified_msg_origin="qq:FriendMessage:10001")

        # 替身要在后台任务真正跑完之前一直生效
        with patch.object(core_tools, "WATCH_INLINE_WAIT", 0.05), \
                patch.object(sys.modules["astrbot.api.event"], "MessageChain", _CapturingChain):
            result = await tool.call(_ctx(event), bvid="BV1QZxWerE3F")
            self.assertEqual(result, WATCH_PENDING_MESSAGE)
            release.set()
            task = plugin._tool_watch_jobs["watch:bv1qzxwere3f"]
            await asyncio.wait({task}, timeout=5)
            await asyncio.sleep(0.05)  # 让 follow-up 任务跑完

        plugin.context.send_message.assert_awaited_once()
        umo, chain = plugin.context.send_message.await_args.args
        self.assertEqual(umo, "qq:FriendMessage:10001")
        # 跟进消息不该把「给模型看的互动提示」原样发给聊天
        self.assertNotIn("如需互动", chain.parts[0])
        self.assertIn("看完啦", chain.parts[0])

    async def test_同一视频不重复开任务(self):
        release = asyncio.Event()

        async def behavior(bvid):
            await release.wait()
            return {"ok": True, "message": "完成", "bvid": bvid}

        plugin = _FakePlugin(behavior)
        tool = _tool(plugin, "watch_video")
        event = types.SimpleNamespace(unified_msg_origin="")
        with patch.object(core_tools, "WATCH_INLINE_WAIT", 0.02):
            first = await tool.call(_ctx(event), bvid="BV1QZxWerE3F")
            second = await tool.call(_ctx(event), bvid="bv1qzxwere3f")
        self.assertEqual(first, WATCH_PENDING_MESSAGE)
        self.assertEqual(second, WATCH_PENDING_MESSAGE)
        self.assertEqual(len(plugin._tool_watch_jobs), 1)
        release.set()
        await asyncio.wait({next(iter(plugin._tool_watch_jobs.values()))}, timeout=5)

    async def test_超过并发上限时拒接新视频(self):
        release = asyncio.Event()

        async def behavior(bvid):
            await release.wait()
            return {"ok": True, "message": "完成", "bvid": bvid}

        plugin = _FakePlugin(behavior)
        tool = _tool(plugin, "watch_video")
        event = types.SimpleNamespace(unified_msg_origin="")
        with patch.object(core_tools, "WATCH_INLINE_WAIT", 0.01):
            for bvid in ("BV1111111111", "BV2222222222", "BV3333333333"):
                await tool.call(_ctx(event), bvid=bvid)
            result = await tool.call(_ctx(event), bvid="BV4444444444")
        self.assertIn("没看完", result)
        release.set()
        await asyncio.wait(set(plugin._tool_watch_jobs.values()), timeout=5)


class _WriteProbe(ProactiveMixin, BilibiliAPIMixin):
    def __init__(self, response):
        self.config = {"BILI_JCT": "csrf", "COMMENT_VERIFY_ENABLED": False}
        self.event_runtime = EventRuntime()
        self.response = response

    async def _http_post(self, url, data=None, **kwargs):
        return self.response, None


class ProactiveFailureReasonTests(unittest.IsolatedAsyncioTestCase):
    async def test_写失败原因进action_reason(self):
        probe = _WriteProbe({"code": 12002, "message": "评论区已关闭"})
        try:
            outcome = await probe._execute_proactive_action(
                "proactive_comment:BV1", "proactive_comment", "BV1",
                lambda: probe._send_comment(1, "看完了"),
            )
        finally:
            await probe.event_runtime.close()
        self.assertFalse(outcome.success)
        self.assertIn("评论区已关闭", outcome.reason)

    async def test_成功时reason保持为空(self):
        probe = _WriteProbe({"code": 0, "data": {"rpid": 7}})
        try:
            outcome = await probe._execute_proactive_action(
                "proactive_like:BV2", "like", "BV2", lambda: probe._like_video(2),
            )
        finally:
            await probe.event_runtime.close()
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.reason, "")


if __name__ == "__main__":
    unittest.main()
