"""post_dynamic 工具：状态透传、ignore_limits、注册开关与自检可用性。

覆盖 2026-11-25 新增能力：
- `_run_dynamic` 返回 (status, detail)，不再只有 bool（避免「说了没做」）；
- 工具主动调用时 `ignore_limits=True` 跳过每日条数与最短间隔；
- 工具按 `BILI_DYNAMIC_TOOL_ENABLED` 条件注册，默认不暴露给模型；
- 自检能回答「为什么发不了动态」。
"""

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

# core/tools.py 还需要 astrbot.core.agent 的桩；test_write_tools 导入时会装好。
import test_write_tools  # noqa: E402,F401

from core.dynamic import DYNAMIC_LOG_FILE, DynamicMixin  # noqa: E402
from core.selftest import _tool_availability  # noqa: E402
from core.tools import create_tools  # noqa: E402


def today_log(count=1):
    from datetime import datetime

    day = datetime.now().strftime("%Y-%m-%d")
    return [{"time": f"{day} 10:0{i}", "text": f"第{i}条"} for i in range(count)]


class DynamicProbe(DynamicMixin):
    def __init__(self, config=None, log=None, content=None):
        self.config = {"DYNAMIC_DAILY_COUNT": 1, **(config or {})}
        self._store = {DYNAMIC_LOG_FILE: list(log if log is not None else [])}
        self._content = content
        self.posted = []

    def _load_json(self, path, default=None):
        return self._store.get(path, default)

    def _save_json(self, path, value):
        self._store[path] = value

    def _autonomous_limit_max(self, _kind):
        return 0

    def _autonomous_plan_for_today(self):
        return {}

    def _dynamic_post_due(self, _log):
        return True

    async def _generate_dynamic_content(self, human_initiated=False):
        if self._content is not None:
            return self._content
        return {"decision": "post", "text": "今天的测试动态", "need_image": False, "image_prompt": ""}

    async def _queue_dynamic_post(self, text, handler):
        self.posted.append(text)
        return True

    async def _save_self_memory_record(self, *args, **kwargs):
        return None


class RunDynamicStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_成功发布返回posted与文案(self):
        probe = DynamicProbe()
        status, detail = await probe._run_dynamic(human_initiated=True)
        self.assertEqual(status, "posted")
        self.assertEqual(detail, "今天的测试动态")

    async def test_达到每日条数时返回skipped_limit(self):
        probe = DynamicProbe(log=today_log(1))
        status, _ = await probe._run_dynamic(human_initiated=True)
        self.assertEqual(status, "skipped_limit")

    async def test_ignore_limits绕过每日条数(self):
        probe = DynamicProbe(log=today_log(3), config={"DYNAMIC_DAILY_COUNT": 1})
        status, detail = await probe._run_dynamic(human_initiated=True, ignore_limits=True)
        self.assertEqual(status, "posted")
        self.assertEqual(len(probe.posted), 1, "应当真的发出去一条")

    async def test_未到间隔时返回skipped_interval(self):
        probe = DynamicProbe()
        probe._dynamic_post_due = lambda _log: False
        status, _ = await probe._run_dynamic(human_initiated=False)
        self.assertEqual(status, "skipped_interval")

    async def test_ignore_limits也绕过最小间隔(self):
        probe = DynamicProbe()
        probe._dynamic_post_due = lambda _log: False
        status, _ = await probe._run_dynamic(human_initiated=False, ignore_limits=True)
        self.assertEqual(status, "posted")

    async def test_生成失败返回failed(self):
        probe = DynamicProbe(content={})
        status, detail = await probe._run_dynamic(human_initiated=True)
        self.assertEqual(status, "failed")
        self.assertIn("生成", detail)

    async def test_没有动机时返回skipped_no_motivation(self):
        probe = DynamicProbe(content={"decision": "skip", "text": ""})
        status, _ = await probe._run_dynamic(human_initiated=True)
        self.assertEqual(status, "skipped_no_motivation")

    async def test_并发时返回skipped_busy(self):
        probe = DynamicProbe()
        lock = asyncio.Lock()
        await lock.acquire()
        probe._dynamic_run_lock = lock
        try:
            status, _ = await probe._run_dynamic(human_initiated=True, ignore_limits=True)
        finally:
            lock.release()
        self.assertEqual(status, "skipped_busy")


def make_plugin(config):
    return types.SimpleNamespace(
        config=dict(config),
        context=types.SimpleNamespace(),
        event_runtime=types.SimpleNamespace(execute=AsyncMock()),
    )


class ToolRegistrationTests(unittest.TestCase):
    def _names(self, config):
        tools = create_tools(make_plugin(config))
        return [tool.name for tool in tools]

    def test_默认不注册发动态工具(self):
        self.assertNotIn("post_dynamic", self._names({"ENABLE_LLM_TOOLS": True}))

    def test_显式开启后注册(self):
        names = self._names({"ENABLE_LLM_TOOLS": True, "BILI_DYNAMIC_TOOL_ENABLED": True})
        self.assertIn("post_dynamic", names)

    def test_私信分享工具同样按开关注册(self):
        self.assertNotIn("watch_and_share_video_private", self._names({"ENABLE_LLM_TOOLS": True}))
        self.assertIn(
            "watch_and_share_video_private",
            self._names({"ENABLE_LLM_TOOLS": True, "BILI_PRIVATE_SHARE_TOOL_ENABLED": True}),
        )

    def test_总开关关闭时不注册任何工具(self):
        """总开关在注册层生效：模型看不到工具，而不是调完才被拒。"""
        self.assertEqual(
            self._names({"ENABLE_LLM_TOOLS": False, "BILI_DYNAMIC_TOOL_ENABLED": True}),
            [],
        )


class SelftestAvailabilityTests(unittest.TestCase):
    def _rows(self, config):
        return {row["key"]: row for row in _tool_availability(make_plugin(config))}

    def test_三个开关都开时发动态可用(self):
        rows = self._rows({
            "ENABLE_LLM_TOOLS": True,
            "ENABLE_DYNAMIC": True,
            "BILI_DYNAMIC_TOOL_ENABLED": True,
        })
        self.assertEqual(rows["工具：发动态"]["value"], "可用")

    def test_未开工具开关时给出缺哪个键(self):
        rows = self._rows({"ENABLE_LLM_TOOLS": True, "ENABLE_DYNAMIC": True})
        row = rows["工具：发动态"]
        self.assertEqual(row["value"], "不可用")
        self.assertIn("BILI_DYNAMIC_TOOL_ENABLED", row["hint"])

    def test_工具总开关关闭时所有写工具都不可用(self):
        rows = self._rows({"ENABLE_LLM_TOOLS": False, "ENABLE_DYNAMIC": True})
        for key in ("工具：发动态", "工具：评论/点赞/投币/收藏", "工具：私信分享视频"):
            self.assertEqual(rows[key]["value"], "不可用", key)
            self.assertIn("ENABLE_LLM_TOOLS", rows[key]["hint"])

    def test_未配置LLM工具开关时按开启处理(self):
        rows = self._rows({"ENABLE_DYNAMIC": True, "BILI_DYNAMIC_TOOL_ENABLED": True})
        self.assertEqual(rows["工具：发动态"]["value"], "可用")


if __name__ == "__main__":
    unittest.main()
