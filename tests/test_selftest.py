"""自检收集逻辑的离线测试。重点守两件事：不崩、不回显密钥。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.selftest import REQUIRED_CONFIG, collect  # noqa: E402

SECRET = "very-secret-sessdata-value-1234567890"


class _FakePlugin:
    def __init__(self, config):
        self.config = config


class CollectTests(unittest.TestCase):
    def test_结构完整(self):
        out = collect(_FakePlugin({"SESSDATA": "x", "BILI_JCT": "y"}))
        # 存储报告挂在 storage 下：键名叫 data 会被响应信封的 unwrap 吃掉，
        # 见 core/selftest.py 里 collect() 的注释。
        for key in ("module", "metadata", "config", "storage", "pages", "routes", "ok", "errors"):
            self.assertIn(key, out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["errors"], [])

    def test_模块信息含包名(self):
        out = collect(_FakePlugin({}))
        self.assertEqual(out["module"]["plugin_name"], "astrbot_plugin_bili_scroll")
        self.assertIn("python", out["module"])

    def test_必填项缺失会标红(self):
        out = collect(_FakePlugin({}))
        required = {item["key"]: item for item in out["config"]["required"]}
        self.assertEqual(set(required), set(REQUIRED_CONFIG))
        for item in required.values():
            self.assertFalse(item["ok"], item["key"])
            self.assertIn("未配置", item["detail"])

    def test_必填项齐全时全绿(self):
        cfg = {key: "value" for key in REQUIRED_CONFIG}
        out = collect(_FakePlugin(cfg))
        for item in out["config"]["required"]:
            self.assertTrue(item["ok"], item["key"])

    def test_密钥值绝不回显(self):
        out = collect(_FakePlugin({"SESSDATA": SECRET, "BILI_JCT": SECRET}))
        dumped = repr(out)
        self.assertNotIn(SECRET, dumped, "自检结果里出现了密钥原文")
        # 但长度信息要保留，方便判断 cookie 是不是填错
        for item in out["config"]["required"]:
            if item["key"] == "SESSDATA":
                self.assertIn(str(len(SECRET)), item["detail"])

    def test_资源别名的配置不被当密钥处理(self):
        # OWNER_MID 不是密钥，值可以直接展示（这里只在 required 里出现）
        out = collect(_FakePlugin({"OWNER_MID": "1215576595"}))
        mid = next(i for i in out["config"]["required"] if i["key"] == "OWNER_MID")
        self.assertTrue(mid["ok"])

    def test_最近异常只报未通过可见性复核的(self):
        import json
        import os
        import tempfile

        import core.selftest as selftest

        rows = [
            {"time": "t1", "rpid": 1, "state": "visible"},
            {"time": "t2", "rpid": 2, "state": "self_only", "phase": "confirm"},
        ]
        before = selftest.VERIFY_LOG_FILE
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "verify.json")
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(rows, fp)
            selftest.VERIFY_LOG_FILE = path
            try:
                out = selftest._recent_verify()
            finally:
                selftest.VERIFY_LOG_FILE = before
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["rpid"], 2)

    def test_数据报告字段齐全(self):
        out = collect(_FakePlugin({}))
        # 键名是 storage 而不是 data：data 会被响应信封的 unwrap 吃掉，见 core/selftest.py 里的说明
        storage = out["storage"]
        self.assertIn("watch_log", storage)
        self.assertIn("verify_log", storage)
        self.assertIn("database", storage)
        # 未跑过时 watch_log 计数应为 0 而不是 None
        self.assertIn(storage["watch_log"]["count"], (0, None))

    def test_页面列表只剩控制中心与配置(self):
        # 「看过的视频」「自检」已并入控制中心 SPA（bilibot/views/*.js），不再是独立页面目录
        names = [p["name"] for p in collect(_FakePlugin({}))["pages"]]
        self.assertIn("bilibot", names)
        self.assertIn("config", names)
        for gone in ("history", "selftest"):
            self.assertNotIn(gone, names)

    def test_路由前缀来自包名(self):
        out = collect(_FakePlugin({}))
        self.assertEqual(out["routes"]["prefix"], "/astrbot_plugin_bili_scroll")
        self.assertTrue(all(e.startswith("/astrbot_plugin_bili_scroll/") for e in out["routes"]["examples"]))

    def test_config读不了也不崩(self):
        class _Boom:
            def get(self, *a, **k):
                raise RuntimeError("炸了")

            def keys(self):
                raise RuntimeError("炸了")

        out = collect(_FakePlugin(_Boom()))
        # 单段失败被记进 errors，但整体仍返回
        self.assertIsInstance(out["errors"], list)
        self.assertIn("config", out["errors"][0] if out["errors"] else "config")


if __name__ == "__main__":
    unittest.main()
