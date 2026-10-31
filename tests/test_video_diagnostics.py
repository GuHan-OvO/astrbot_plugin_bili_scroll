"""Exercise diagnostic capture, disk persistence, rendering and task isolation offline."""
import ast
import asyncio
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_autonomous_ranges import ProactiveProbe
from test_video_evaluation import payload
from core.llm import LLMMixin
from core.proactive import ProactiveMixin
from core.utils import UtilsMixin
from core.video import VideoMixin
from core.video_diagnostics import (
    get_call_diagnostic, set_call_diagnostic, safe_detail, media_failure,
)
import core.proactive as proactive_module
import core.watch_log as watch_log_module


class EvaluationBot(ProactiveProbe, LLMMixin):
    def __init__(self):
        super().__init__({"LLM_PROVIDER_ID": "test-provider", "LLM_CIRCUIT_FAILURE_THRESHOLD": 0})
        self._get_system_prompt = AsyncMock(return_value="private persona")
        self._load_json = lambda path, default: default
        self._get_today_mood = lambda: ("平静", "")
        self._owner_recommendation_context = AsyncMock(return_value="")
        self._format_recent_taste_summary = lambda _: ""
        self._format_recent_preference_summary = lambda _: ""
        self.context = types.SimpleNamespace(llm_generate=AsyncMock())

    def response(self, text):
        self.context.llm_generate.return_value = types.SimpleNamespace(completion_text=text)


class VideoFrameCountTests(unittest.IsolatedAsyncioTestCase):
    """每段送几帧必须跟着档位走，而不是写死 5。"""

    async def _count_for(self, depth):
        bot = VideoMixin()
        bot.config = {"ANALYSIS_DEPTH": depth}
        bot._extract_video_frames = AsyncMock(return_value=[])
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "seg0.mp4"
            clip.write_bytes(b"video")
            await bot._analyze_single_segment(
                str(clip), {"title": "t", "bvid": "BVtest"}, "none", "provider", None, "model",
            )
        return bot._extract_video_frames.await_args.kwargs["count"]

    async def test_标准档保持原版5帧(self):
        self.assertEqual(await self._count_for("standard"), 5)

    async def test_无限制档每段12帧(self):
        self.assertEqual(await self._count_for("unlimited"), 12)

    async def test_帧数为0时跳过截帧(self):
        bot = VideoMixin()
        bot.config = {"ANALYSIS_DEPTH": "subtitle_only", "MEDIA_MAX_FRAMES": 0}
        bot._extract_video_frames = AsyncMock(return_value=[])
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "seg0.mp4"
            clip.write_bytes(b"video")
            self.assertIsNone(await bot._analyze_single_segment(
                str(clip), {"title": "t", "bvid": "BVtest"}, "none", "provider", None, "model",
            ))
        bot._extract_video_frames.assert_not_called()

    def test_切片段数跟着档位走(self):
        bot = VideoMixin()
        bot.config = {"ANALYSIS_DEPTH": "unlimited", "VIDEO_SEGMENT_MINUTES": 5}
        self.assertEqual(bot._segment_limits(), (300, 360))
        # 非自定义档忽略单项配置（档位值覆盖），这正是 deep/无限制档原先失效的地方
        bot.config = {"ANALYSIS_DEPTH": "standard", "VIDEO_SEGMENT_MINUTES": 5,
                      "VIDEO_SEGMENT_MAX_COUNT": 4}
        self.assertEqual(bot._segment_limits(), (300, 10))
        bot.config = {"ANALYSIS_DEPTH": "custom", "VIDEO_SEGMENT_MINUTES": 3,
                      "VIDEO_SEGMENT_MAX_COUNT": 7}
        self.assertEqual(bot._segment_limits(), (180, 7))


class VideoDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_reason_shape_and_no_model_prose(self):
        bot = EvaluationBot()
        bot.response('{"score": 9, "private": "DO_NOT_STORE_MODEL_TEXT"}')
        info = {"bvid": "BVtest", "analysis_basis": "video_media"}
        self.assertIsNone(await bot._evaluate_video(info, "content"))
        detail = info["_evaluation_diagnostic"]
        self.assertEqual(detail["stage"], "evaluation_schema")
        self.assertEqual(detail["reason"], "evaluation_schema_mismatch")
        self.assertIn("review", detail["missing_fields"])
        self.assertEqual(detail["extra_field_count"], 1)
        self.assertEqual(detail["model_call"]["provider"], "test-provider")
        self.assertNotIn("DO_NOT_STORE", json.dumps(detail))

    async def test_invalid_json_records_length_and_error_position(self):
        bot = EvaluationBot(); bot.response('{"score":')
        info = {}
        await bot._evaluate_video(info, "content")
        detail = info["_evaluation_diagnostic"]
        self.assertEqual(detail["reason"], "invalid_json")
        self.assertEqual(detail["response_chars"], 9)
        self.assertEqual(detail["json_error_position"], 9)

    async def test_http_error_status_is_preserved_and_secret_removed(self):
        bot = EvaluationBot()
        bot.config["GENERATION_API_KEY"] = "private-token-42"
        bot.config["GENERATION_PROVIDER_ID"] = "test-provider"
        exc = RuntimeError("rate limit private-token-42 https://host/key/private-token-42")
        exc.status_code = 429
        bot.context.llm_generate.side_effect = exc
        info = {}
        await bot._evaluate_video(info, "content")
        detail = info["_evaluation_diagnostic"]
        self.assertEqual(detail["stage"], "model_request")
        self.assertIn("HTTP 429", detail["reason"])
        self.assertNotIn("private-token-42", json.dumps(detail))
        self.assertNotIn("https://host", json.dumps(detail))

    async def test_empty_circuit_and_success_do_not_reuse_previous_error(self):
        bot = EvaluationBot(); bot.response("")
        info = {}
        await bot._evaluate_video(info, "content")
        self.assertEqual(info["_evaluation_diagnostic"]["reason"], "模型返回空内容")
        bot.config["LLM_CIRCUIT_FAILURE_THRESHOLD"] = 1
        bot._enter_llm_circuit = AsyncMock(return_value=None)
        bot._last_llm_error = ""
        await bot._evaluate_video(info, "content")
        self.assertEqual(info["_evaluation_diagnostic"]["model_call"]["stage"], "circuit")
        bot._enter_llm_circuit = AsyncMock(return_value="disabled")
        bot.response(json.dumps(payload()))
        result = await bot._evaluate_video(info, "content")
        self.assertEqual(result["score"], 8.6)
        self.assertNotIn("_evaluation_diagnostic", info)

    async def test_content_skip_does_not_call_model_and_keeps_media_failure(self):
        bot = EvaluationBot()
        info = {"analysis_basis": "metadata"}
        media_failure(info, "download", "HTTP 403", {})
        await bot._evaluate_video(info, "content")
        self.assertEqual(info["_evaluation_diagnostic"]["stage"], "content")
        self.assertEqual(info["_evaluation_diagnostic"]["media_errors"][0]["reason"], "HTTP 403")
        bot.context.llm_generate.assert_not_awaited()

    async def test_preparation_exception_is_recorded(self):
        bot = EvaluationBot()
        bot._get_system_prompt.side_effect = RuntimeError("persona unavailable")
        info = {}
        self.assertIsNone(await bot._evaluate_video(info, "content"))
        self.assertIn("persona unavailable", info["_evaluation_diagnostic"]["reason"])

    async def test_concurrent_calls_do_not_exchange_error_reasons(self):
        bot = EvaluationBot()
        async def generate(**kwargs):
            marker = "first" if "FIRST_VIDEO" in kwargs["prompt"] else "second"
            await asyncio.sleep(0.01 if marker == "first" else 0)
            raise TimeoutError(marker)
        bot.context.llm_generate.side_effect = generate
        one, two = {}, {}
        await asyncio.gather(bot._evaluate_video(one, "FIRST_VIDEO"), bot._evaluate_video(two, "SECOND_VIDEO"))
        self.assertEqual(one["_evaluation_diagnostic"]["reason"], "TimeoutError: first")
        self.assertEqual(two["_evaluation_diagnostic"]["reason"], "TimeoutError: second")

    async def test_cancellation_still_propagates(self):
        bot = EvaluationBot()
        bot.context.llm_generate.side_effect = asyncio.CancelledError()
        info = {}
        with self.assertRaises(asyncio.CancelledError):
            await bot._evaluate_video(info, "content")
        self.assertNotIn("_evaluation_diagnostic", info)

    async def test_missing_vision_configuration_records_cause(self):
        bot = types.SimpleNamespace(config={}, _get_video_vision_client=lambda: None)
        info = {"bvid": "BVtest"}
        self.assertIsNone(await VideoMixin._analyze_video_media(bot, info))
        self.assertEqual(info["_media_diagnostics"][0]["stage"], "vision_config")

    async def test_failed_download_records_underlying_reason(self):
        async def download(_):
            set_call_diagnostic(reason="HTTP 403")
            return None
        # vision_key / dead-reason probes are part of _analyze_video_media now; the stub
        # must answer them or the flow never reaches the download stage this test asserts.
        bot = types.SimpleNamespace(config={"VIDEO_VISION_PROVIDER_ID": "vision"},
            _get_video_vision_client=lambda: None, _detect_video_format=lambda _: "none",
            _video_direct_key=lambda *a: ("", "", "", ""), _video_vision_dead_reason=lambda *_: None,
            _download_video=download)
        info = {"bvid": "BVtest"}
        await VideoMixin._analyze_video_media(bot, info)
        self.assertEqual(info["_media_diagnostics"][0]["reason"], "HTTP 403")

    async def test_special_follow_persists_and_renderer_reads_after_reload(self):
        await self.check_persistence("special")

    async def test_regular_watch_persists_and_renderer_reads_after_reload(self):
        await self.check_persistence("regular")

    async def check_persistence(self, flow):
        class DiskBot(ProactiveMixin, UtilsMixin):
            pass
        bot = DiskBot()
        bot.config = {"PROACTIVE_FOLLOW_UIDS": ["42"]}
        bot._seen_video_bvids = AsyncMock(return_value=set())
        bot._get_up_latest_video = AsyncMock(return_value={"bvid": "BVtest", "title": "test", "up_name": "UP", "oid": 1, "up_mid": "42"})
        bot._reserve_proactive_watch = AsyncMock(return_value=types.SimpleNamespace(success=True))
        bot._get_video_info = AsyncMock(return_value={})
        async def analyze(info):
            info["analysis_basis"] = "metadata"
            media_failure(info, "download", "HTTP 403", {})
            return "metadata only"
        bot._analyze_video_with_vision = analyze
        bot._get_environment_status = lambda: {"features": {"proactive_video_media": True}}
        bot.get_followings = AsyncMock(return_value=[])
        bot._get_pool_videos = AsyncMock(return_value=[])
        bot._decide_proactive_search_queries = AsyncMock(return_value=[])
        bot._get_proactive_search_videos = AsyncMock(return_value=[])
        bot._get_taste_tids = lambda: []
        bot._should_watch_video_before_download = AsyncMock(return_value=(True, ""))
        with tempfile.TemporaryDirectory() as directory:
            names = ("WATCH_LOG_FILE", "COMMENTED_FILE", "EXTERNAL_MEMORY_FILE", "PROACTIVE_LOG_FILE", "OWNER_RECOMMEND_LOG_FILE")
            paths = {name: str(Path(directory) / (name + ".json")) for name in names}
            archive = str(Path(directory) / "archive")
            with patch.multiple(proactive_module, **paths), patch.multiple(
                watch_log_module,
                WATCH_LOG_FILE=paths["WATCH_LOG_FILE"],
                archive_dir=lambda: archive,
            ):
                if flow == "special":
                    await bot._run_special_follow_inner()
                else:
                    await bot._run_proactive_inner(max_watch=1)
            stored = json.loads(Path(paths["WATCH_LOG_FILE"]).read_text(encoding="utf-8"))
            self.assertEqual(stored[0]["evaluation_status"], "failed")
            self.assertEqual(stored[0]["diagnostic"]["media_errors"][0]["reason"], "HTTP 403")
            # Load the real renderer without starting AstrBot or calling any API.
            tree = ast.parse((Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8"))
            method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_render_video_log")
            scope = dict(paths)
            exec(compile(ast.Module(body=[method], type_ignores=[]), "main.py", "exec"), scope)
            text = scope["_render_video_log"](UtilsMixin(), stored[0]["time"][:10], True)
            self.assertIn("未评分", text)
            self.assertIn("HTTP 403", text)
            self.assertNotIn("0分", text)
            stored[0].pop("diagnostic"); stored[0].pop("evaluation_status")
            Path(paths["WATCH_LOG_FILE"]).write_text(json.dumps(stored), encoding="utf-8")
            text = scope["_render_video_log"](UtilsMixin(), stored[0]["time"][:10], True)
            self.assertIn("旧记录未保存原因", text)

    def test_bounds_and_redaction(self):
        info = {}
        for _ in range(30):
            media_failure(info, "test", "x" * 1000, {})
        self.assertEqual(len(info["_media_diagnostics"]), 8)
        self.assertLessEqual(len(info["_media_diagnostics"][0]["reason"]), 300)
        result = safe_detail('api_key="abc" Bearer secret-token https://host/secret sk-abc_xyz')
        for secret in ("abc", "secret-token", "host/secret", "sk-"):
            self.assertNotIn(secret, result)


class ProactiveWatchSuccessPathTests(unittest.IsolatedAsyncioTestCase):
    """评分成功的观看必须一路走到长期记忆，而不是中途异常退出。

    回归：核心流程把落账改成内联字典后，仍有两处引用重构前的 log_entry，
    任何一次成功观看都会在最关键的「写长期记忆」之前 NameError 退出。
    原有 regular 流程的用例走的是「评价失败 continue」分支，覆盖不到这一段。
    """

    async def test_watch_success_writes_long_term_memory(self):
        class DiskBot(ProactiveMixin, VideoMixin, UtilsMixin):
            pass

        bot = DiskBot()
        bot.config = {"PROACTIVE_FOLLOW_UIDS": ["42"]}
        bot._seen_video_bvids = AsyncMock(return_value=set())
        bot._get_up_latest_video = AsyncMock(return_value={
            "bvid": "BVtest", "title": "test", "up_name": "UP", "oid": 1, "up_mid": "42",
        })
        bot._reserve_proactive_watch = AsyncMock(return_value=types.SimpleNamespace(success=True))
        bot._get_video_info = AsyncMock(return_value={})

        async def analyze(info):
            info["analysis_basis"] = "metadata"
            return "metadata only"

        bot._analyze_video_with_vision = analyze
        bot._get_environment_status = lambda: {"features": {"proactive_video_media": True}}
        bot.get_followings = AsyncMock(return_value=[])
        bot._get_pool_videos = AsyncMock(return_value=[])
        bot._decide_proactive_search_queries = AsyncMock(return_value=[])
        bot._get_proactive_search_videos = AsyncMock(return_value=[])
        bot._get_taste_tids = lambda: []
        bot._should_watch_video_before_download = AsyncMock(return_value=(True, ""))
        bot._evaluate_video = AsyncMock(return_value=payload())
        # Cookie 判定失效：互动段整体跳过，只验证「看完 → 落记录 → 写记忆」这一段。
        bot.check_cookie = AsyncMock(return_value=(False, ""))
        bot._save_self_memory_record = AsyncMock()

        names = (
            "WATCH_LOG_FILE", "COMMENTED_FILE", "EXTERNAL_MEMORY_FILE",
            "PROACTIVE_LOG_FILE", "OWNER_RECOMMEND_LOG_FILE", "VIDEO_MEMORY_FILE",
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = {name: str(Path(directory) / (name + ".json")) for name in names}
            archive = str(Path(directory) / "archive")
            with patch.multiple(proactive_module, **paths), patch.multiple(
                watch_log_module,
                WATCH_LOG_FILE=paths["WATCH_LOG_FILE"],
                archive_dir=lambda: archive,
            ), patch.object(proactive_module.random, "randint", return_value=0):
                await bot._run_proactive_inner(max_watch=1)

            stored = json.loads(Path(paths["WATCH_LOG_FILE"]).read_text(encoding="utf-8"))
            self.assertEqual(stored[0]["bvid"], "BVtest")
            self.assertEqual(stored[0]["score"], 8.6)
            self.assertEqual(stored[0]["actions"], [])
            cache = json.loads(Path(paths["VIDEO_MEMORY_FILE"]).read_text(encoding="utf-8"))
            self.assertEqual(cache["BVtest"]["score"], 8.6)

        bot._save_self_memory_record.assert_awaited_once()
        thread_id, text = bot._save_self_memory_record.await_args.args[:2]
        self.assertEqual(thread_id, "proactive_watch")
        self.assertIn("Bot看了视频《test》", text)
        self.assertEqual(bot._save_self_memory_record.await_args.kwargs["extra"]["bvid"], "BVtest")
