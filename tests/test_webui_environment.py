"""基础设置页「环境与配置」卡片依赖的只读端点（不启动 AstrBot）。"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 复用 test_webui_interest 里那套更完整的 astrbot 桩
from test_webui_interest import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.webui_bridge import handle_get_environment  # noqa: E402


def _payload(response):
    """``_response`` 返回 json_response 封装，取出业务载荷。"""
    body = getattr(response, "body", None)
    if body is None and isinstance(response, dict):
        body = response
    body = body or {}
    text = body.get("body")
    if isinstance(text, (bytes, bytearray)):
        body = json.loads(text.decode("utf-8"))
    return body


class _FakePlugin:
    def __init__(self, status=None, error=None):
        self._status = status
        self._error = error

    def _get_environment_status(self):
        if self._error:
            raise self._error
        return self._status


class WebuiEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_原样返回环境自检结果(self):
        status = {
            "external_commands": {"yt-dlp": True, "ffmpeg": False, "ffprobe": False},
            "llm": {"chat_provider": True},
            "features": {"web_search": False},
        }
        payload = _payload(await handle_get_environment(_FakePlugin(status=status)))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"], status)

    async def test_自检抛异常时返回错误而不是500崩溃(self):
        payload = _payload(await handle_get_environment(_FakePlugin(error=RuntimeError("boom"))))
        self.assertEqual(payload["status"], "error")
        self.assertIn("boom", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
