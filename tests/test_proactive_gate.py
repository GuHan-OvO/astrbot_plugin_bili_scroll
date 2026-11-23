"""issue #3：额度已满时不能把「任务已创建」说成「已经在看视频」。

覆盖三层：
1. `_proactive_gate_reason` 的各条拒绝分支与原因文案；
2. `_maybe_trigger_proactive_from_llm` 在额度满时不建任务、注入「没有开始」；
3. `_run_proactive_inner` 被拦住时把原因返回给调用方（供后台补一句提示）；
4. AST 锁 main.py 两处入口确实先过同一道门禁。
"""

import ast
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

import core.proactive as proactive_module  # noqa: E402
from core.config import WATCH_LOG_FILE  # noqa: E402
from core.proactive import ProactiveMixin  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


class _DoneTask:
    def done(self):
        return True


class _RunningTask:
    def done(self):
        return False


class GateProbe(ProactiveMixin):
    def __init__(self, config, watch_log=None, authed=True):
        self.config = dict(config)
        self._store = {WATCH_LOG_FILE: list(watch_log or [])}
        self._authed = authed
        self._proactive_task = None
        self.injected = []

    def _load_json(self, path, default=None):
        return self._store.get(path, default)

    def _save_json(self, path, value):
        self._store[path] = value

    def _has_cookie(self):
        return self._authed

    def _autonomous_limit_max(self, _kind):
        return 0

    def _get_environment_status(self):
        return {"features": {"proactive_video_media": True}}


def today_watches(count):
    from datetime import datetime

    day = datetime.now().strftime("%Y-%m-%d")
    return [
        {"time": f"{day} 0{i}:00", "bvid": f"BVfake{i}", "score": 8.0, "comment": "不错"}
        for i in range(count)
    ]


class GateReasonTests(unittest.TestCase):
    def test_功能没开时直接拒绝(self):
        probe = GateProbe({"ENABLE_PROACTIVE": False})
        ok, reason = probe._proactive_gate_reason()
        self.assertFalse(ok)
        self.assertIn("没开", reason)

    def test_没登录时拒绝(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True}, authed=False)
        ok, reason = probe._proactive_gate_reason()
        self.assertFalse(ok)
        self.assertIn("登录", reason)

    def test_已有任务在跑时拒绝(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True})
        probe._proactive_task = _RunningTask()
        ok, reason = probe._proactive_gate_reason()
        self.assertFalse(ok)
        self.assertIn("已经有一轮", reason)

    def test_额度用完时拒绝并给出计数(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 2}, watch_log=today_watches(2))
        ok, reason = probe._proactive_gate_reason()
        self.assertFalse(ok)
        self.assertIn("额度用完", reason)
        self.assertIn("2", reason)

    def test_额度未满时放行(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 3}, watch_log=today_watches(2))
        ok, reason = probe._proactive_gate_reason()
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_评价失败次数达上限时拒绝(self):
        failed = today_watches(3)
        for item in failed:
            item["evaluation_status"] = "failed"
        probe = GateProbe(
            {"ENABLE_PROACTIVE": True, "PROACTIVE_FAILED_WATCH_MAX": 3},
            watch_log=failed,
        )
        ok, reason = probe._proactive_gate_reason()
        self.assertFalse(ok)
        self.assertIn("失败", reason)

    def test_评价失败的观看不吃额度(self):
        log = today_watches(2)
        log[0]["evaluation_status"] = "failed"
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 2}, watch_log=log)
        ok, _ = probe._proactive_gate_reason()
        self.assertTrue(ok, "失败的那条不算看过，额度应还剩 1 个")


class LlmTriggerTests(unittest.IsolatedAsyncioTestCase):
    def _event(self):
        return types.SimpleNamespace(
            message_str="你去随便刷点B站视频",
            unified_msg_origin="test:group:1",
            get_sender_name=lambda: "主人",
        )

    async def test_额度满时不建任务也不说已开始(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 2}, watch_log=today_watches(2))
        req = types.SimpleNamespace(extra_user_content_parts=[])
        probe._should_trigger_proactive_from_text = AsyncMock(return_value=True)
        probe._run_proactive = AsyncMock()
        with patch.object(proactive_module, "inject_temp_context", lambda _req, text: probe.injected.append(text) or True):
            await probe._maybe_trigger_proactive_from_llm(self._event(), req)
        self.assertIsNone(probe._proactive_task, "额度满时不应创建任务")
        probe._run_proactive.assert_not_awaited()
        self.assertTrue(probe.injected, "应当把「没有开始」注入给模型")
        text = probe.injected[0]
        self.assertIn("没有开始", text)
        self.assertIn("额度用完", text)
        self.assertNotIn("已在后台开始执行", text)

    async def test_额度未满时正常受理(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 3}, watch_log=today_watches(1))
        req = types.SimpleNamespace(extra_user_content_parts=[])
        probe._should_trigger_proactive_from_text = AsyncMock(return_value=True)

        async def noop(**_kwargs):
            return ""

        probe._run_proactive = noop
        with patch.object(proactive_module, "inject_temp_context", lambda _req, text: probe.injected.append(text) or True):
            await probe._maybe_trigger_proactive_from_llm(self._event(), req)
            await asyncio.sleep(0)
        self.assertIsNotNone(probe._proactive_task)
        self.assertIn("已在后台开始执行", probe.injected[0])

    async def test_功能没开时不跑意图判断(self):
        probe = GateProbe({"ENABLE_PROACTIVE": False})
        probe._should_trigger_proactive_from_text = AsyncMock(return_value=True)
        await probe._maybe_trigger_proactive_from_llm(self._event(), types.SimpleNamespace())
        probe._should_trigger_proactive_from_text.assert_not_awaited()


class InnerSkipReasonTests(unittest.IsolatedAsyncioTestCase):
    async def test_额度满时返回原因而不是None(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 2}, watch_log=today_watches(2))
        reason = await probe._run_proactive_inner(max_watch=1)
        self.assertTrue(reason, "被拦住时必须把原因返回给调用方")
        self.assertIn("不再刷", reason)

    async def test_正常路径返回空串(self):
        probe = GateProbe({"ENABLE_PROACTIVE": True, "PROACTIVE_DAILY_LIMIT": 3})
        probe._get_pool_videos = AsyncMock(return_value=[])
        probe._get_fav_pool_videos = AsyncMock(return_value=[])
        probe.get_followings = AsyncMock(return_value=[])
        probe._seen_video_bvids = AsyncMock(return_value=set())
        probe._decide_proactive_search_queries = AsyncMock(return_value=[])
        probe._get_proactive_search_videos = AsyncMock(return_value=[])
        probe._get_taste_tids = lambda: []
        probe._should_watch_video_before_download = AsyncMock(return_value=(True, ""))
        probe._evaluate_video = AsyncMock(return_value=None)
        probe._save_self_memory_record = AsyncMock()
        probe._set_cross_platform_activity = lambda *_a, **_k: None
        probe._clear_cross_platform_activity = lambda *_a, **_k: None
        names = (
            "WATCH_LOG_FILE", "COMMENTED_FILE", "EXTERNAL_MEMORY_FILE",
            "PROACTIVE_LOG_FILE", "OWNER_RECOMMEND_LOG_FILE", "VIDEO_MEMORY_FILE",
        )
        with patch.multiple(proactive_module, **{name: "unused" for name in names}), patch.object(
            proactive_module.random, "randint", return_value=0
        ):
            reason = await probe._run_proactive_inner(max_watch=1)
        self.assertEqual(reason, "")


class MainEntryGateTests(unittest.TestCase):
    """main.py 的两处入口必须先过门禁，不能再无条件回「已触发」。"""

    def _method(self, name):
        tree = ast.parse((REPO / "main.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
                return node
        raise AssertionError(f"main.py 里没找到 {name}")

    def _calls_gate(self, node):
        return any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_proactive_gate_reason"
            for call in ast.walk(node)
        )

    def test_命令入口先过门禁(self):
        self.assertTrue(self._calls_gate(self._method("cmd_proactive")))

    def test_工具入口先过门禁(self):
        self.assertTrue(self._calls_gate(self._method("_tool_bili_watch_videos_result")))


if __name__ == "__main__":
    unittest.main()
