"""首屏引导的后端状态测试（不启动 AstrBot，只测判断逻辑）。"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 复用 test_webui_interest 里那套更完整的 astrbot 桩（含 astrbot.api.star.Context）
from test_webui_interest import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.config import ONBOARDING_FILE  # noqa: E402
from core.webui_bridge import handle_get_onboarding  # noqa: E402


class _FakePlugin:
    def __init__(self, config=None, store=None):
        self.config = dict(config or {})
        self.store = dict(store or {})

    def _load_json(self, path, default):
        return self.store.get(path, default)

    def _save_json(self, path, value):
        self.store[path] = value


def _payload(response):
    """``_response`` 返回的是 json_response 封装，取出业务载荷。"""
    body = getattr(response, "body", None)
    if body is None and isinstance(response, dict):
        body = response
    return body or {}


class OnboardingTests(unittest.TestCase):
    def _data(self, plugin):
        response = asyncio.run(handle_get_onboarding(plugin))
        payload = _payload(response)
        text = payload.get("body")
        if isinstance(text, (bytes, bytearray)):
            import json

            payload = json.loads(text.decode("utf-8"))
        return payload.get("data", payload)

    def test_没点过不再弹出就一直弹(self):
        data = self._data(_FakePlugin())
        self.assertTrue(data["should_show"])
        self.assertFalse(data["dismissed"])

    def test_点过不再弹出后不再弹(self):
        plugin = _FakePlugin(store={ONBOARDING_FILE: {"dismissed": True}})
        data = self._data(plugin)
        self.assertFalse(data["should_show"])

    def test_完成度按真实配置算(self):
        plugin = _FakePlugin(config={
            "SESSDATA": "x",
            "OWNER_MID": "10000000001",
            "OWNER_BILI_NAME": "某人",
            "ENABLE_PROACTIVE": True,
        })
        data = self._data(plugin)
        self.assertEqual(data["completed"], {"login": True, "owner": True, "proactive": True})

    def test_缺一项就算未完成(self):
        plugin = _FakePlugin(config={"SESSDATA": "x", "OWNER_MID": "10000000001"})
        data = self._data(plugin)
        self.assertTrue(data["completed"]["login"])
        self.assertFalse(data["completed"]["owner"], "只有 UID 没有昵称，@ 不到人")
        self.assertFalse(data["completed"]["proactive"])


if __name__ == "__main__":
    unittest.main()
