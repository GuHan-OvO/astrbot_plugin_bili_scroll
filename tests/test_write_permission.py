"""写工具调用者权限：默认只有管理员能触发 B站 写操作。

覆盖 2026-11-25 加固：
- `BILI_WRITE_TOOL_PERMISSION` 三档：admin_only（默认）/ follow_host / anyone；
- 拿不到会话时按拒绝处理（写操作宁可不做）；
- 顺带锁住 `ToolExecResult(...)` 不能再被当类调用（它是 str | CallToolResult 的 union 别名，
  B站拉黑工具曾因此一调就 TypeError）。
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_write_tools import _FakePlugin  # noqa: E402

import core.tools as core_tools  # noqa: E402
from core.selftest import _tool_availability  # noqa: E402
from core.tools import create_tools  # noqa: E402


class _PermPlugin(_FakePlugin):
    def __init__(self, mode=None):
        super().__init__()
        if mode is None:
            self.config.pop("BILI_WRITE_TOOL_PERMISSION", None)
        else:
            self.config["BILI_WRITE_TOOL_PERMISSION"] = mode


def ctx(*, admin=True):
    event = types.SimpleNamespace(is_admin=lambda: admin)
    return types.SimpleNamespace(context=types.SimpleNamespace(event=event))


def tools(plugin):
    return {tool.name: tool for tool in create_tools(plugin)}


class WritePermissionTests(unittest.IsolatedAsyncioTestCase):
    async def _like(self, plugin, context):
        tool = tools(plugin)["bili_action"]
        with patch.object(core_tools.random, "uniform", return_value=0):
            return await tool.call(context, action="like", target="4242")

    async def test_默认档位只允许管理员(self):
        plugin = _PermPlugin()
        denied = await self._like(plugin, ctx(admin=False))
        self.assertIn("只能由管理员", denied)
        self.assertEqual(plugin.event_runtime.requests, [], "被拒绝时不该发出写请求")

        ok = await self._like(_PermPlugin(), ctx(admin=True))
        self.assertIn("点赞成功", ok)

    async def test_拿不到会话时按拒绝处理(self):
        result = await self._like(_PermPlugin(), None)
        self.assertIn("只能由管理员", result)

    async def test_跟随上游档位不自己判断(self):
        plugin = _PermPlugin("follow_host")
        result = await self._like(plugin, ctx(admin=False))
        self.assertIn("点赞成功", result)

    async def test_不限制档位放行任何人(self):
        plugin = _PermPlugin("anyone")
        result = await self._like(plugin, ctx(admin=False))
        self.assertIn("点赞成功", result)

    async def test_发动态工具把text透传下去(self):
        plugin = _PermPlugin("anyone")
        plugin.config["BILI_DYNAMIC_TOOL_ENABLED"] = True
        captured = {}

        async def fake_run(human_initiated=False, ignore_limits=False, text=""):
            captured.update(human_initiated=human_initiated, ignore_limits=ignore_limits, text=text)
            return "posted", text

        plugin._run_dynamic = fake_run
        tool = tools(plugin)["bili_post_dynamic"]
        result = await tool.call(ctx(admin=True), text="  主模型写的  ")
        self.assertEqual(captured["text"], "主模型写的", "前后空白应被裁掉")
        self.assertTrue(captured["ignore_limits"], "工具仍应绕过每日条数与间隔")
        self.assertIn("已发动态", result)

    async def test_发动态工具同样受权限约束(self):
        plugin = _PermPlugin()
        plugin.config["BILI_DYNAMIC_TOOL_ENABLED"] = True
        tool = tools(plugin)["bili_post_dynamic"]
        result = await tool.call(ctx(admin=False))
        self.assertIn("只能由管理员", result)


class ToolExecResultMisuseTests(unittest.TestCase):
    def test_不再把union别名当类调用(self):
        source = (ROOT / "core" / "tools.py").read_text(encoding="utf-8")
        self.assertNotIn("ToolExecResult(", source)


class SelftestWriteScopeTests(unittest.TestCase):
    def test_自检标出调用范围(self):
        plugin = types.SimpleNamespace(config={"BILI_WRITE_TOOL_PERMISSION": "admin_only"})
        rows = {row["key"]: row for row in _tool_availability(plugin)}
        self.assertIn("仅管理员", rows["工具：发动态"]["hint"])

    def test_默认缺省也标仅管理员(self):
        plugin = types.SimpleNamespace(config={})
        rows = {row["key"]: row for row in _tool_availability(plugin)}
        self.assertIn("仅管理员", rows["工具：评论/点赞/投币/收藏"]["hint"])


if __name__ == "__main__":
    unittest.main()
