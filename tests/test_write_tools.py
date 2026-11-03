"""写操作工具回归：视频标识解析 + 失败原因透传。

覆盖 issue #2（`bili_action` 把 BV 号当整数转换，评论永远失败且只回「失败」）：
- `_resolve_video_aid` 接受数字 aid / av 号 / BV 号 / 视频链接，解析失败给可读原因；
- 四个写操作工具都走这个解析，不再 `int()` 崩掉；
- `_send_comment` 的 B站 code 会回给 LLM（例如「评论区已关闭」），而不是只剩日志。

纯离线：不连 AstrBot、不发网络请求。
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()


def _install_agent_stubs():
    """core/tools.py 需要的 astrbot.core.agent 契约（真实环境由 AstrBot 提供）。"""
    astrbot = sys.modules["astrbot"]
    if isinstance(getattr(astrbot, "core", None), types.ModuleType):
        return

    class FunctionTool:
        def __class_getitem__(cls, item):
            return cls

    class _ContextWrapper:
        def __class_getitem__(cls, item):
            return cls

    class AstrAgentContext:
        pass

    tool_module = types.ModuleType("astrbot.core.agent.tool")
    tool_module.FunctionTool = FunctionTool
    tool_module.ToolExecResult = str
    run_context = types.ModuleType("astrbot.core.agent.run_context")
    run_context.ContextWrapper = _ContextWrapper
    astr_agent_context = types.ModuleType("astrbot.core.astr_agent_context")
    astr_agent_context.AstrAgentContext = AstrAgentContext

    core = types.ModuleType("astrbot.core")
    core.__path__ = []
    agent = types.ModuleType("astrbot.core.agent")
    agent.__path__ = []
    astrbot.core = core
    core.agent = agent
    agent.tool = tool_module
    agent.run_context = run_context
    sys.modules.update({
        "astrbot.core": core,
        "astrbot.core.agent": agent,
        "astrbot.core.agent.tool": tool_module,
        "astrbot.core.agent.run_context": run_context,
        "astrbot.core.astr_agent_context": astr_agent_context,
    })


_install_agent_stubs()

import core.tools as core_tools  # noqa: E402
from core.bilibili import BilibiliAPIMixin  # noqa: E402
from core.tools import create_tools  # noqa: E402


class _FakeRuntime:
    """最小事件运行时：直接跑 handler，返回 ActionOutcome 的等价物。"""

    def __init__(self):
        self.requests = []

    async def execute(self, request, handler, success=None):
        self.requests.append(request)
        value = handler()
        if hasattr(value, "__await__"):
            value = await value
        ok = success(value) if success is not None else bool(value)
        return types.SimpleNamespace(
            success=ok,
            value=value,
            reason="" if ok else "handler_returned_unsuccessful",
            state="succeeded" if ok else "failed",
        )


class _FakePlugin(BilibiliAPIMixin):
    def __init__(self, *, post_response=None, aid=4242):
        self.config = {
            "DEDE_USER_ID": "10001",
            "OWNER_MID": "10002",
            "OWNER_NAME": "主人",
            "BILI_JCT": "csrf",
            "ENABLE_LLM_TOOLS": True,
            "COMMENT_VERIFY_ENABLED": False,
        }
        self.event_runtime = _FakeRuntime()
        self.post_response = post_response or {"code": 0, "data": {"rpid": 99}}
        self.aid = aid
        self.get_calls = []

    async def _http_get(self, url, params=None, **kwargs):
        self.get_calls.append((url, params))
        return {"code": 0, "data": {"aid": self.aid, "bvid": "BV1QZxWerE3F"}}, None

    async def _http_post(self, url, data=None, **kwargs):
        return self.post_response, None


class ResolveVideoAidTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = _FakePlugin(aid=4242)

    async def test_数字aid原样返回(self):
        self.assertEqual(await self.plugin._resolve_video_aid(" 10001 "), (10001, ""))

    async def test_av号转aid(self):
        self.assertEqual(await self.plugin._resolve_video_aid("av10001"), (10001, ""))

    async def test_视频链接里的av号(self):
        self.assertEqual(
            await self.plugin._resolve_video_aid("https://www.bilibili.com/video/av10001"),
            (10001, ""),
        )

    async def test_BV号查询aid并保留大小写(self):
        self.assertEqual(await self.plugin._resolve_video_aid("BV1QZxWerE3F"), (4242, ""))
        url, params = self.plugin.get_calls[-1]
        self.assertEqual(params, {"bvid": "BV1QZxWerE3F"})

    async def test_视频链接里的BV号(self):
        self.assertEqual(
            await self.plugin._resolve_video_aid("https://www.bilibili.com/video/BV1QZxWerE3F?p=2"),
            (4242, ""),
        )

    async def test_链接里的aid参数(self):
        self.assertEqual(
            await self.plugin._resolve_video_aid("https://www.bilibili.com/video?aid=777"),
            (777, ""),
        )

    async def test_无法识别时给出可读原因(self):
        aid, error = await self.plugin._resolve_video_aid("这期视频")
        self.assertIsNone(aid)
        self.assertIn("无法识别", error)

    async def test_空标识(self):
        aid, error = await self.plugin._resolve_video_aid("")
        self.assertIsNone(aid)
        self.assertIn("缺少视频标识", error)


class WriteToolRoutingTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self, plugin):
        return {tool.name: tool for tool in create_tools(plugin)}

    async def test_bili_action用BV号发评论(self):
        plugin = _FakePlugin()
        tool = self._tools(plugin)["bili_action"]
        result = await tool.call(
            None, action="comment", target="BV1QZxWerE3F", text="@主人 看完了"
        )
        self.assertIn("评论成功", result)
        # 落到写操作队列的是数字 aid，不是 BV 字符串
        self.assertEqual(plugin.event_runtime.requests[0].target_id, "4242")

    async def test_评论失败时透传B站code(self):
        plugin = _FakePlugin(post_response={"code": 12002, "message": "评论区已关闭"})
        tool = self._tools(plugin)["bili_action"]
        result = await tool.call(
            None, action="comment", target="4242", text="看完了"
        )
        self.assertIn("评论区已关闭", result)
        self.assertNotIn("int()", result)

    async def test_无法识别的标识不发写请求(self):
        plugin = _FakePlugin()
        tool = self._tools(plugin)["bili_action"]
        result = await tool.call(None, action="like", target="这期视频")
        self.assertIn("无法识别", result)
        self.assertEqual(plugin.event_runtime.requests, [])

    async def test_点赞接受BV号(self):
        plugin = _FakePlugin()
        tool = self._tools(plugin)["bili_action"]
        with patch.object(core_tools.random, "uniform", return_value=0):
            result = await tool.call(None, action="like", target="BV1QZxWerE3F")
        self.assertIn("点赞成功", result)
        self.assertEqual(plugin.event_runtime.requests[0].target_id, "4242")

    async def test_投币接受BV号(self):
        plugin = _FakePlugin()
        tool = self._tools(plugin)["bili_action"]
        with patch.object(core_tools.random, "uniform", return_value=0):
            result = await tool.call(None, action="coin", target="BV1QZxWerE3F", num=2)
        self.assertIn("投了2个币", result)


if __name__ == "__main__":
    unittest.main()
