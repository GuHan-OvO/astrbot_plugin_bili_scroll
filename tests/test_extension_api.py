"""对外状态门面的契约测试（对应 private_companion 7.0.0 的 provider 校验）。"""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.extension_api import (  # noqa: E402
    PLUGIN_ID,
    STATUS_SCHEMA,
    BiliBotExtensionApi,
)


class _FakePlugin:
    def __init__(self, config):
        self.config = config


class _ExplodingConfig:
    def get(self, *_args, **_kwargs):
        raise RuntimeError("配置读不了")


class CompanionStatusContractTests(unittest.TestCase):
    def test_必须是同步函数(self):
        api = BiliBotExtensionApi(_FakePlugin({}))
        # PC 侧明确拒绝 async：await 会 ValueError
        self.assertFalse(inspect.iscoroutinefunction(api.companion_v2_status))

    def test_schema与plugin_id与PC常量一致(self):
        status = BiliBotExtensionApi(_FakePlugin({})).companion_v2_status()
        self.assertEqual(status["schema"], "companion.provider-status.v1")
        self.assertEqual(status["schema"], STATUS_SCHEMA)
        self.assertEqual(status["plugin_id"], "astrbot_plugin_bili_scroll")
        self.assertEqual(status["plugin_id"], PLUGIN_ID)

    def test_enabled必须是bool(self):
        for cfg, expected in (
            ({"ENABLE_PROACTIVE": True}, True),
            ({"ENABLE_PROACTIVE": False}, False),
            ({}, False),
            ({"ENABLE_PROACTIVE": "yes"}, True),
        ):
            status = BiliBotExtensionApi(_FakePlugin(cfg)).companion_v2_status()
            self.assertIs(type(status["enabled"]), bool, f"cfg={cfg}")
            self.assertEqual(status["enabled"], expected, f"cfg={cfg}")

    def test_runtime_ready有cookie为True无cookie为False(self):
        with_cookie = BiliBotExtensionApi(
            _FakePlugin({"SESSDATA": "abc"})
        ).companion_v2_status()
        without = BiliBotExtensionApi(_FakePlugin({})).companion_v2_status()
        blank = BiliBotExtensionApi(_FakePlugin({"SESSDATA": "   "})).companion_v2_status()

        self.assertIs(with_cookie["runtime_ready"], True)
        self.assertIs(without["runtime_ready"], False)
        self.assertIs(blank["runtime_ready"], False)

    def test_配置读不了不抛异常且返回合法类型(self):
        status = BiliBotExtensionApi(_ExplodingConfig()).companion_v2_status()
        self.assertIs(type(status["enabled"]), bool)
        self.assertIn(status["runtime_ready"], (None, True, False))
        self.assertEqual(status["schema"], STATUS_SCHEMA)

    def test_只暴露状态不暴露能力(self):
        api = BiliBotExtensionApi(_FakePlugin({}))
        public = [n for n in dir(api) if not n.startswith("_")]
        # 门面只该有版本号与状态方法；多出来的可调用能力意味着它真的能驱动什么
        self.assertEqual(sorted(public), ["api_version", "companion_v2_status"])


if __name__ == "__main__":
    unittest.main()
