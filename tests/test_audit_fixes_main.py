"""Offline regression tests for the 2026-10-06 audit fixes owned by main agent.

Covers:
- F2: management commands must carry the ADMIN permission filter.
- F3: /bili绑定 cannot self-declare OWNER_MID; owner context injection needs admin.
- #34: schedule plan model is configurable, retries are configurable, and the
  plan JSON extractor falls back to the LLM JSON repair helper.

All tests are offline: no AstrBot instance, no network, fabricated config only.
"""
import ast
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"

ADMIN_COMMANDS = {
    "cmd_login", "cmd_login_confirm", "cmd_live_danmaku", "cmd_start", "cmd_stop",
    "cmd_proactive", "cmd_toggle", "cmd_refresh_cookie", "cmd_consolidation",
    "cmd_weekly_summary", "cmd_cleanup_aged", "cmd_block", "cmd_unblock",
    "cmd_cleanup", "cmd_personality_edit", "cmd_personality_delete",
    "cmd_permanent_memory", "cmd_dynamic", "cmd_watch_bangumi", "cmd_umo",
}

USER_FACING_COMMANDS = {"cmd_bind", "cmd_memory", "cmd_affection", "cmd_help", "cmd_status"}


def _main_class_tree():
    tree = ast.parse(MAIN.read_text(encoding="utf-8-sig"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BiliBiliBot"
    )


def _load_methods(names, namespace):
    cls = _main_class_tree()
    functions = [
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    assert {n.name for n in functions} == set(names)
    for node in functions:
        node.decorator_list = []
        node.returns = None
        for arg in node.args.args + node.args.kwonlyargs:
            arg.annotation = None
    namespace.setdefault("__package__", "audit_plugin")
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), str(MAIN), "exec"),
        namespace,
    )
    return {name: namespace[name] for name in names}


class AdminPermissionDecoratorTests(unittest.TestCase):
    def test_management_commands_require_admin(self):
        cls = _main_class_tree()
        decorated = {}
        for node in cls.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if any("command(" in d for d in decorators):
                decorated[node.name] = decorators
        for name in sorted(ADMIN_COMMANDS):
            with self.subTest(command=name):
                self.assertIn(name, decorated, f"{name} 不再是命令？测试需要更新")
                self.assertTrue(
                    any("permission_type" in d and "ADMIN" in d for d in decorated[name]),
                    f"{name} 缺少 @filter.permission_type(filter.PermissionType.ADMIN)",
                )

    def test_user_facing_commands_stay_open(self):
        cls = _main_class_tree()
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in USER_FACING_COMMANDS:
                decorators = [ast.unparse(d) for d in node.decorator_list]
                self.assertFalse(
                    any("permission_type" in d for d in decorators),
                    f"{node.name} 是普通用户功能，不应加管理员限制",
                )


class Event:
    def __init__(self, text, sender="20002", admin=False):
        self.message_str = text
        self.sender = sender
        self._admin = admin
        self.unified_msg_origin = f"audit:FriendMessage:{sender}"
        self.message_obj = types.SimpleNamespace(raw_message=None, message=[])

    def plain_result(self, text):
        return text

    def get_sender_id(self):
        return self.sender

    def is_admin(self):
        return self._admin


class BindSecurityTests(unittest.IsolatedAsyncioTestCase):
    def _bot(self, bindings_file, owner_mid="10001"):
        namespace = {"BINDING_FILE": str(bindings_file)}
        methods = _load_methods(["cmd_bind"], namespace)
        bot = types.SimpleNamespace(
            config={"OWNER_MID": owner_mid},
            _load_json=lambda path, default=None: default if default is not None else {},
            _save_json=MagicMock(),
        )
        return methods["cmd_bind"], bot

    async def test_non_admin_cannot_bind_owner_uid(self):
        with tempfile.TemporaryDirectory() as temp:
            cmd_bind, bot = self._bot(Path(temp) / "bindings.json")
            event = Event("/bili绑定 10001", admin=False)
            replies = [item async for item in cmd_bind(bot, event)]
            self.assertIn("管理员", replies[-1])
            bot._save_json.assert_not_called()

    async def test_admin_can_bind_owner_uid(self):
        with tempfile.TemporaryDirectory() as temp:
            cmd_bind, bot = self._bot(Path(temp) / "bindings.json")
            event = Event("/bili绑定 10001", admin=True)
            replies = [item async for item in cmd_bind(bot, event)]
            self.assertIn("已绑定", replies[-1])
            bot._save_json.assert_called_once()

    async def test_normal_user_can_bind_own_uid(self):
        with tempfile.TemporaryDirectory() as temp:
            cmd_bind, bot = self._bot(Path(temp) / "bindings.json")
            event = Event("/bili绑定 33333", admin=False)
            replies = [item async for item in cmd_bind(bot, event)]
            self.assertIn("已绑定", replies[-1])


class OwnerInjectionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_bound_to_owner_gets_no_owner_context(self):
        with tempfile.TemporaryDirectory() as temp:
            bindings = Path(temp) / "bindings.json"
            bindings.write_text(json.dumps({"20002": "10001"}), encoding="utf-8")
            namespace = {"BINDING_FILE": str(bindings)}
            methods = _load_methods(["inject_bili_memory"], namespace)

            bot = types.SimpleNamespace(
                config={
                    "OWNER_MID": "10001",
                    "ENABLE_CROSS_PLATFORM_ACTIVITY_STATUS": True,
                    "MEMORY_ISOLATION_MODE": "safe_share",
                    "ENABLE_SAFE_CROSS_PLATFORM_MEMORY": True,
                },
                _maybe_trigger_proactive_from_llm=AsyncMock(),
                _inject_recent_group_share_into_request=MagicMock(return_value=False),
                _load_json=lambda path, default=None: json.loads(bindings.read_text(encoding="utf-8")),
                _cross_platform_activity_context=lambda: "OWNER_SECRET_ACTIVITY",
                _inject_context_block_before_user=MagicMock(return_value=True),
                memory_api=types.SimpleNamespace(
                    get_recent_memories=MagicMock(return_value=[
                        {"memory_type": "chat", "text": "OWNER_SECRET_MEMORY_TEXT"}
                    ])
                ),
            )
            req = types.SimpleNamespace(prompt="今天做了什么", system_prompt="")
            event = Event("今天做了什么", admin=False)
            await methods["inject_bili_memory"](bot, event, req)
            self.assertNotIn("OWNER_SECRET", req.prompt)
            bot.memory_api.get_recent_memories.assert_not_called()


class OwnerInjectionMemoryTests(unittest.IsolatedAsyncioTestCase):
    """issue #1：主动刷视频写入的记忆 user_id="self"，按绑定 UID 查询会全部漏掉。"""

    def _fake_redact_modules(self):
        modules = {
            "audit_plugin": types.ModuleType("audit_plugin"),
            "audit_plugin.core": types.ModuleType("audit_plugin.core"),
            "audit_plugin.core.security": types.ModuleType("audit_plugin.core.security"),
            "audit_plugin.core.security.redact": types.ModuleType("audit_plugin.core.security.redact"),
        }
        modules["audit_plugin"].__path__ = [str(ROOT)]
        modules["audit_plugin.core"].__path__ = [str(ROOT / "core")]
        modules["audit_plugin.core.security"].__path__ = [str(ROOT / "core" / "security")]
        redact = modules["audit_plugin.core.security.redact"]
        redact.contains_credentials = lambda text: False
        redact.redact_outbound = lambda text, internal=False: (text, [])
        return modules

    async def test_self_video_memory_reaches_owner_context(self):
        with tempfile.TemporaryDirectory() as temp:
            bindings = Path(temp) / "bindings.json"
            bindings.write_text(json.dumps({"20002": "10001"}), encoding="utf-8")
            namespace = {
                "BINDING_FILE": str(bindings),
                "logger": types.SimpleNamespace(
                    debug=MagicMock(), info=MagicMock(), warning=MagicMock(), error=MagicMock()
                ),
            }
            methods = _load_methods(["inject_bili_memory"], namespace)
            memory_api = types.SimpleNamespace(
                get_recent_memories=MagicMock(return_value=[
                    {
                        "memory_type": "video",
                        "user_id": "self",
                        "text": "[2026-11-01 23:00] Bot看了视频《手工皮具保姆级新手指南》评分 7.5/10",
                    },
                ])
            )
            injected = {}
            bot = types.SimpleNamespace(
                config={
                    "OWNER_MID": "10001",
                    "ENABLE_CROSS_PLATFORM_ACTIVITY_STATUS": False,
                    "MEMORY_ISOLATION_MODE": "safe_share",
                    "ENABLE_SAFE_CROSS_PLATFORM_MEMORY": True,
                    "CROSS_PLATFORM_MEMORY_PROMPT": "只当轻量背景",
                    "MEMORY_BLOCKED_PREFIXES": [],
                    "MEMORY_BLOCKED_KEYWORDS": [],
                },
                _maybe_trigger_proactive_from_llm=AsyncMock(),
                _inject_recent_group_share_into_request=MagicMock(return_value=False),
                _load_json=lambda path, default=None: json.loads(bindings.read_text(encoding="utf-8")),
                _cross_platform_activity_context=lambda: "",
                _inject_context_block_before_user=MagicMock(
                    side_effect=lambda req, block: injected.setdefault("block", block) or True
                ),
                memory_api=memory_api,
            )
            req = types.SimpleNamespace(prompt="今天做了什么", system_prompt="")
            event = Event("今天做了什么", admin=True)

            modules = self._fake_redact_modules()
            saved = {name: sys.modules.get(name) for name in modules}
            sys.modules.update(modules)
            try:
                await methods["inject_bili_memory"](bot, event, req)
            finally:
                for name, value in saved.items():
                    if value is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = value

            # 按绑定 UID 查询时必须并入 self 活动，否则主动看视频的记忆永远查不到
            self.assertIs(memory_api.get_recent_memories.call_args.kwargs.get("include_self"), True)
            self.assertIn("手工皮具", injected.get("block", ""))


def _load_schedule_mixin(temp_dir):
    package = types.ModuleType("audit_sched_core")
    package.__path__ = [str(ROOT / "core")]
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = MagicMock()
    astrbot.api = api
    config = types.ModuleType("audit_sched_core.config")
    for name in (
        "AUTONOMOUS_PLAN_FILE", "BANGUMI_SCHEDULE_FILE", "DYNAMIC_SCHEDULE_FILE",
        "DYNAMIC_WATCH_SCHEDULE_FILE", "SCHEDULE_FILE", "SPECIAL_FOLLOW_SCHEDULE_FILE",
    ):
        setattr(config, name, str(Path(temp_dir) / f"{name.lower()}.json"))
    with unittest.mock.patch.dict(sys.modules, {
        "audit_sched_core": package,
        "audit_sched_core.config": config,
        "astrbot": astrbot,
        "astrbot.api": api,
    }):
        spec = importlib.util.spec_from_file_location(
            "audit_sched_core.schedule_mixin", ROOT / "core" / "schedule_mixin.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


class SchedulePlanConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.module = _load_schedule_mixin(self.temp.name)

    def test_max_attempts_respects_config(self):
        mixin = self.module.ScheduleMixin()
        mixin.config = {}
        self.assertEqual(mixin._autonomous_plan_max_attempts(), 3)  # 1 + 2 retries
        mixin.config = {"AUTONOMOUS_PLAN_MAX_RETRIES": 0}
        self.assertEqual(mixin._autonomous_plan_max_attempts(), 1)
        mixin.config = {"AUTONOMOUS_PLAN_MAX_RETRIES": 5}
        self.assertEqual(mixin._autonomous_plan_max_attempts(), 6)
        mixin.config = {"AUTONOMOUS_PLAN_MAX_RETRIES": "junk"}
        self.assertEqual(mixin._autonomous_plan_max_attempts(), 3)

    def test_extract_plan_json_uses_repair_fallback(self):
        mixin = self.module.ScheduleMixin()
        mixin.config = {}
        # Mimic UtilsMixin._repair_llm_json behaviour for fenced/trailing-comma JSON.
        def repair(text):
            text = text.replace("```json", "").replace("```", "").strip()
            import re as _re
            return _re.sub(r",\s*([}\]])", r"\1", text)
        mixin._repair_llm_json = repair
        raw = '```json\n{"proactive_windows": ["10:00-11:00",], "rationale": "ok",}\n```'
        plan = mixin._extract_plan_json(raw)
        self.assertEqual(plan.get("rationale"), "ok")
        self.assertEqual(plan.get("proactive_windows"), ["10:00-11:00"])

    def test_extract_plan_json_without_repair_still_works(self):
        mixin = self.module.ScheduleMixin()
        mixin.config = {}
        plan = mixin._extract_plan_json('noise {"dynamic_times": ["20:00"]} tail')
        self.assertEqual(plan.get("dynamic_times"), ["20:00"])


class ScheduleProviderPassthroughTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_llm_call_uses_configured_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            module = _load_schedule_mixin(temp)
            mixin = module.ScheduleMixin()
            captured = {}

            async def fake_llm(prompt, system_prompt="", max_tokens=300, provider_id=None):
                captured["provider_id"] = provider_id
                return '{"proactive_windows": [], "rationale": "quiet"}'

            mixin.config = {
                "ENABLE_AUTONOMOUS_DAILY_PLAN": True,
                "SCHEDULE_PLAN_PROVIDER_ID": "plan-model-01",
                "AUTONOMOUS_PLAN_GENERATION_MODE": "fixed",
                "AUTONOMOUS_PLAN_GENERATION_TIME": "00:00",
                "AUTONOMOUS_MIN_ACTION_GAP_MINUTES": 45,
                "AUTONOMOUS_ACTIVITY_LEVEL": 55,
                "AUTONOMOUS_PROACTIVE_WINDOW_MINUTES": 90,
                "SLEEP_START": 2, "SLEEP_END": 8,
                "PROACTIVE_TIMES_COUNT": 2, "PROACTIVE_DAILY_LIMIT": 4,
                "DYNAMIC_TIMES_COUNT": 1, "DYNAMIC_DAILY_COUNT": 1,
                "BANGUMI_DAILY_LIMIT": 1, "SPECIAL_FOLLOW_TIMES_COUNT": 1,
                "DYNAMIC_WATCH_TIMES_COUNT": 2,
                "AUTONOMOUS_PLAN_PROMPT": "",
            }
            mixin._llm_call = fake_llm
            mixin._get_today_mood = lambda: ("平静", "")
            mixin._get_system_prompt = AsyncMock(return_value="persona")
            mixin._autonomous_generation_due = lambda: True
            mixin._schedule_feature_enabled = lambda kind: True
            mixin._load_json = lambda path, default=None: default if default is not None else {}
            saved = {}
            mixin._save_json = lambda path, data: saved.setdefault(str(path), data)
            mixin._save_schedule_state = lambda *a, **k: None
            mixin._save_dynamic_schedule_state = lambda *a, **k: None
            mixin._save_bangumi_schedule_state = lambda *a, **k: None
            mixin._save_special_follow_schedule_state = lambda *a, **k: None
            mixin._save_dynamic_watch_schedule_state = lambda *a, **k: None

            plan = await mixin._ensure_autonomous_daily_plan(force=True)
            self.assertEqual(captured.get("provider_id"), "plan-model-01")
            self.assertEqual(plan.get("generation_status"), "success")


if __name__ == "__main__":
    unittest.main()
