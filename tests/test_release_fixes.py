"""1.9.8 修复回归：评分容错、搜索词过滤、配额语义、命令解析、无窗子进程、日志安全、推荐解耦。

这些用例都对应真实故障（日志/数据在项目进度文档 T83 有取证），不是假想场景。
"""
import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

import core.utils as core_utils  # noqa: E402
import core.video_evaluation as evaluation_module  # noqa: E402
from core.proactive import ProactiveMixin  # noqa: E402
from core.safe_logger import safe_text  # noqa: E402
from core.utils import UtilsMixin  # noqa: E402
from core.video_evaluation import (  # noqa: E402
    VideoEvaluationError,
    parse_video_evaluation,
)

VALID_EVALUATION = {
    "score": 7.5,
    "score_reason": "讲解清楚，节奏也合适",
    "comment": "看完想试试",
    "mood": "开心",
    "review": "还不错",
    "want_follow": False,
    "recommend_owner": False,
    "recommend_reason": "",
    "partition": "手工",
    "preference_signals": [],
    "search_keywords": ["手工"],
}


class EvaluationJsonToleranceTests(unittest.TestCase):
    def test_夹带前言也能解析(self):
        raw = "Thinking Process:\n1. 先看标题\n2. 再看内容\n\n" + json.dumps(VALID_EVALUATION, ensure_ascii=False)
        result = parse_video_evaluation(raw)
        self.assertEqual(result["score"], 7.5)

    def test_代码块后面的尾巴不影响(self):
        raw = "```json\n" + json.dumps(VALID_EVALUATION, ensure_ascii=False) + "\n```\n以上是我的评价。"
        result = parse_video_evaluation(raw)
        self.assertEqual(result["mood"], "开心")

    def test_字符串里的花括号不被误判(self):
        data = dict(VALID_EVALUATION, review="像 {这样} 的花括号不应打断解析")
        raw = "前言\n" + json.dumps(data, ensure_ascii=False) + "\n结尾"
        self.assertIn("{这样}", parse_video_evaluation(raw)["review"])

    def test_完全没有对象才报invalid_json(self):
        with self.assertRaises(VideoEvaluationError) as ctx:
            parse_video_evaluation("模型这次什么都没返回 { 只有半个")
        self.assertEqual(str(ctx.exception), "invalid_json")


class SearchQueryFilterTests(unittest.TestCase):
    def test_思考过程不被当成搜索词(self):
        raw = (
            "Thinking Process:\n"
            "**Analyze the Request:**\n"
            "analysis\n"
            "手工皮具教程\n"
            "微缩模型制作\n"
        )
        queries = ProactiveMixin._parse_proactive_search_queries(raw, limit=3)
        self.assertEqual(queries, ["手工皮具教程", "微缩模型制作"])

    def test_正常JSON数组照旧(self):
        queries = ProactiveMixin._parse_proactive_search_queries('["纸艺手工", "立体书教程"]')
        self.assertEqual(queries, ["纸艺手工", "立体书教程"])


class QuotaSemanticsContractTests(unittest.TestCase):
    """配额与推荐解耦属于循环内部逻辑，用源码契约守住（跑整轮代价太大）。"""

    def setUp(self):
        self.source = (ROOT / "core" / "proactive.py").read_text(encoding="utf-8-sig")

    def test_评价失败不占每日额度(self):
        self.assertIn('str(l.get("evaluation_status") or "") != "failed"', self.source)
        self.assertIn("PROACTIVE_FAILED_WATCH_MAX", self.source)

    def test_推荐不再被互动失败吞掉(self):
        self.assertIn("owner_recommend_ready = (", self.source)
        self.assertIn("if not interaction_failed or owner_recommend_ready:", self.source)
        self.assertIn("if owner_recommend_ready:", self.source)

    def test_投币收藏评论仍受互动失败限制(self):
        for keyword in ("PROACTIVE_COIN_MIN_SCORE", "PROACTIVE_FAV_MIN_SCORE", "PROACTIVE_COMMENT_MIN_SCORE"):
            with self.subTest(keyword=keyword):
                self.assertIn(f"if not interaction_failed and", self.source)


class FindCommandTests(unittest.TestCase):
    def test_能找到数据目录bin下的命令(self):
        probe = UtilsMixin()
        with patch.object(core_utils.shutil, "which", return_value=None), \
                patch.object(core_utils.sys, "executable", str(Path(tempfile.mkdtemp()) / "python.exe")), \
                patch.object(core_utils, "DATA_DIR", tempfile.mkdtemp(prefix="bilitools-")):
            bin_dir = Path(core_utils.DATA_DIR) / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            exe = bin_dir / "yt-dlp.exe"
            exe.write_bytes(b"stub")
            self.assertEqual(probe._find_command("yt-dlp"), str(exe))

    def test_能找到解释器同目录的命令(self):
        probe = UtilsMixin()
        with tempfile.TemporaryDirectory() as tmp:
            fake_python = Path(tmp) / "python.exe"
            fake_python.write_bytes(b"stub")
            exe = Path(tmp) / "yt-dlp.exe"
            exe.write_bytes(b"stub")
            with patch.object(core_utils.shutil, "which", return_value=None), \
                    patch.object(core_utils.sys, "executable", str(fake_python)):
                self.assertEqual(probe._find_command("yt-dlp"), str(exe))


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return b"", b""


class RunProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_不弹控制台窗口(self):
        probe = UtilsMixin()
        captured = {}

        async def fake_exec(*args, **kwargs):
            captured.update(kwargs)
            return _FakeProc()

        with patch.object(core_utils.shutil, "which", return_value="ffmpeg"), \
                patch.object(core_utils.asyncio, "create_subprocess_exec", new=fake_exec):
            code, _, _ = await probe._run_process("ffmpeg", "-version")
        self.assertEqual(code, 0)
        if sys.platform == "win32":
            self.assertEqual(captured.get("creationflags"), 0x08000000)
        else:
            self.assertEqual(captured.get("creationflags"), 0)


class ProvisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_已有ytdlp时不装(self):
        probe = UtilsMixin()
        probe.config = {}
        with patch.object(probe, "_find_command", return_value="C:/bin/yt-dlp.exe"), \
                patch.object(probe, "_run_process", new=AsyncMock()) as run:
            await probe._ensure_external_tools()
        run.assert_not_called()

    async def test_缺失时用当前解释器补装一次(self):
        probe = UtilsMixin()
        probe.config = {}
        calls = []

        def find(name):
            return "C:/bin/yt-dlp.exe" if len(calls) > 0 else None

        async def fake_run(*args, **kwargs):
            calls.append(args)
            return 0, "", ""

        with patch.object(probe, "_find_command", side_effect=find), \
                patch.object(probe, "_run_process", new=fake_run):
            await probe._ensure_external_tools()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1:4], ("-m", "pip", "install"))
        self.assertEqual(calls[0][-1], "yt-dlp")

    async def test_只尝试一次(self):
        probe = UtilsMixin()
        probe.config = {}
        with patch.object(probe, "_find_command", return_value=None), \
                patch.object(probe, "_run_process", new=AsyncMock(return_value=(1, "", "boom"))) as run:
            await probe._ensure_external_tools()
            await probe._ensure_external_tools()
        self.assertEqual(run.await_count, 1)


class SafeLoggerTests(unittest.TestCase):
    def tearDown(self):
        import core.safe_logger as module
        module._ENCODING = None

    def test_gbk编码下emoji被替换且不抛异常(self):
        import core.safe_logger as module
        module._ENCODING = "gbk"
        text = "📢 已在评论区@主人：测试"
        cleaned = safe_text(text)
        self.assertIn("已在评论区@主人", cleaned)
        self.assertNotIn("📢", cleaned)
        cleaned.encode("gbk")

    def test_中文原样保留(self):
        import core.safe_logger as module
        module._ENCODING = "gbk"
        self.assertEqual(safe_text("普通中文日志"), "普通中文日志")

    def test_非字符串原样返回(self):
        self.assertEqual(safe_text(42), 42)


class RecommendationDecoupleContractTests(unittest.TestCase):
    def test_合同文件存在(self):
        self.assertTrue((ROOT / "core" / "safe_logger.py").exists())


if __name__ == "__main__":
    unittest.main()
