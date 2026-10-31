"""临时上下文注入：不得改 system_prompt，也不得写进会话历史。

回归自插件市场审核：主动触发与分享背景曾直接改写 req.system_prompt / req.messages，
前者让系统提示词前缀缓存每轮失效，后者会把背景写进会话历史。

注：本仓库部分测试模块会在 sys.modules 里装假的 astrbot 包，且不还原；因此除最后一条
守护测试外，这里显式给注入器喂一个替身 ContentPart，不依赖真实 AstrBot 是否可用。
"""

import types
import unittest
from unittest.mock import AsyncMock, patch

from core import request_context
from core.proactive import ProactiveMixin
from core.share import ShareMixin


class FakeTextPart:
    """模仿 astrbot.core.agent.message.TextPart 的最小契约。"""

    def __init__(self, text):
        self.text = text
        self._no_save = False

    def mark_as_temp(self):
        self._no_save = True
        return self

    def model_dump_for_context(self):
        data = {"type": "text", "text": self.text}
        if self._no_save:
            data["_no_save"] = True
        return data


class TempContextPartTests(unittest.TestCase):
    def test_injects_marked_temp_part_without_touching_prompts(self):
        req = types.SimpleNamespace(
            extra_user_content_parts=[], system_prompt="persona", prompt="用户原话"
        )
        with patch.object(request_context, "_get_text_part", lambda: FakeTextPart):
            self.assertTrue(request_context.inject_temp_context(req, "背景块"))
        self.assertEqual(len(req.extra_user_content_parts), 1)
        part = req.extra_user_content_parts[0]
        self.assertEqual(part.text, "背景块")
        self.assertTrue(part._no_save, "临时片段必须标记为不落盘")
        self.assertEqual(part.model_dump_for_context()["_no_save"], True)
        self.assertEqual(req.system_prompt, "persona")
        self.assertEqual(req.prompt, "用户原话")

    def test_blank_block_is_ignored(self):
        req = types.SimpleNamespace(extra_user_content_parts=[], system_prompt="", prompt="hi")
        self.assertFalse(request_context.inject_temp_context(req, "   "))
        self.assertEqual(req.extra_user_content_parts, [])

    def test_request_without_extra_parts_reports_failure(self):
        self.assertFalse(
            request_context.inject_temp_context(types.SimpleNamespace(prompt="hi"), "block")
        )

    def test_missing_mark_as_temp_still_injects(self):
        """老版本没有 mark_as_temp 时仍要注入，只是不保证不进历史。"""

        class BarePart:
            def __init__(self, text):
                self.text = text

        with patch.object(request_context, "_get_text_part", lambda: BarePart):
            req = types.SimpleNamespace(extra_user_content_parts=[])
            self.assertTrue(request_context.inject_temp_context(req, "block"))
            self.assertEqual(req.extra_user_content_parts[0].text, "block")

    def test_unsupported_environment_reports_failure(self):
        """取不到 TextPart 时明确失败，调用方据此走 prompt 兜底，而不是改 system_prompt。"""
        with patch.object(request_context, "_get_text_part", lambda: None):
            req = types.SimpleNamespace(extra_user_content_parts=[])
            self.assertFalse(request_context.inject_temp_context(req, "block"))

    def test_real_astrbot_part_is_temp_marked(self):
        """守护真实依赖：AstrBot 的 ContentPart 必须提供 mark_as_temp 且 dump 出 _no_save。"""
        try:
            from astrbot.core.agent.message import TextPart as RealTextPart
        except Exception:
            self.skipTest("当前测试会话的 astrbot 可能被桩模块替换，无法验证真实 TextPart")
        part = RealTextPart(text="x")
        self.assertTrue(hasattr(part, "mark_as_temp"), "AstrBot 缺少 mark_as_temp，临时注入会进历史")
        part.mark_as_temp()
        self.assertTrue(part._no_save)
        self.assertTrue(part.model_dump_for_context().get("_no_save"))


class ShareInjectionTests(unittest.TestCase):
    def test_share_context_goes_to_temp_parts(self):
        bot = ShareMixin()
        req = types.SimpleNamespace(
            extra_user_content_parts=[], system_prompt="persona", prompt="用户原话"
        )
        with patch.object(request_context, "_get_text_part", lambda: FakeTextPart):
            self.assertTrue(bot._inject_context_block_before_user(req, "【上一条会话背景】"))
        self.assertEqual(len(req.extra_user_content_parts), 1)
        self.assertEqual(req.system_prompt, "persona")
        self.assertEqual(req.prompt, "用户原话")

    def test_falls_back_to_prompt_but_never_system_prompt(self):
        bot = ShareMixin()
        req = types.SimpleNamespace(system_prompt="persona", prompt="用户原话")
        with patch.object(request_context, "_get_text_part", lambda: None):
            self.assertTrue(bot._inject_context_block_before_user(req, "背景"))
        self.assertTrue(req.prompt.startswith("背景"))
        self.assertEqual(req.system_prompt, "persona")


class ProactiveTriggerInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_trigger_does_not_touch_system_prompt(self):
        bot = types.SimpleNamespace(
            config={"ENABLE_PROACTIVE": True},
            _has_cookie=lambda: True,
            _proactive_task=None,
            _run_proactive=AsyncMock(),
            _should_trigger_proactive_from_text=AsyncMock(return_value=True),
            _load_json=lambda path, default=None: [],
            _save_json=lambda path, data: None,
        )
        req = types.SimpleNamespace(extra_user_content_parts=[], system_prompt="persona")
        event = types.SimpleNamespace(
            get_sender_name=lambda: "小明", message_str="去看视频"
        )
        try:
            with patch.object(request_context, "_get_text_part", lambda: FakeTextPart):
                await ProactiveMixin._maybe_trigger_proactive_from_llm(bot, event, req)
            self.assertEqual(req.system_prompt, "persona")
            self.assertEqual(len(req.extra_user_content_parts), 1)
            self.assertIn("小明", req.extra_user_content_parts[0].text)
        finally:
            task = bot._proactive_task
            if task is not None:
                task.cancel()


if __name__ == "__main__":
    unittest.main()
