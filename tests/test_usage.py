"""用量台账的离线测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.usage import (  # noqa: E402
    KEEP_DAYS,
    collect,
    load,
    make_entry,
    record,
    summarize,
)

NOW = 1_793_000_000.0  # 固定时间，避免跨零点抖动


def _entry(**over):
    base = make_entry(purpose="GENERATION", model="m1", input_other=1000, input_cached=500, output=200, now=NOW)
        # make_entry 返回的是缩写键（in / cached_in / out），over 里也要用缩写
    base.update(over)
    return base


class MakeEntryTests(unittest.TestCase):
    def test_字段齐全且非负(self):
        e = make_entry(purpose="X", model="m", input_other=-5, input_cached=10, output=3, now=NOW)
        self.assertEqual(set(e), {"ts", "day", "purpose", "model", "in", "cached_in", "out", "media_cached"})
        self.assertEqual(e["in"], 0, "负数要被夹成 0")
        self.assertEqual(e["cached_in"], 10)

    def test_空用途给默认值(self):
        self.assertEqual(make_entry(purpose="", now=NOW)["purpose"], "chat")

    def test_模型名截断(self):
        self.assertLessEqual(len(make_entry(purpose="x", model="m" * 200, now=NOW)["model"]), 80)


class SummarizeTests(unittest.TestCase):
    def test_单条聚合(self):
        out = summarize([_entry()], days=1, now=NOW)
        w = out["window"]
        self.assertEqual(w["calls"], 1)
        self.assertEqual(w["input_other"], 1000)
        self.assertEqual(w["input_cached"], 500)
        self.assertEqual(w["output"], 200)
        self.assertEqual(w["total_input"], 1500)
        self.assertEqual(w["total_tokens"], 1700)
        self.assertAlmostEqual(w["cache_hit_ratio"], 500 / 1500, places=4)

    def test_按用途与模型分组(self):
        rows = [
            _entry(purpose="GENERATION", model="a", out=10),
            _entry(purpose="GENERATION", model="a", out=20),
            _entry(purpose="SUMMARY", model="b", out=30),
        ]
        out = summarize(rows, days=1, now=NOW)
        self.assertEqual(out["by_purpose"]["GENERATION"]["calls"], 2)
        self.assertEqual(out["by_purpose"]["GENERATION"]["output"], 30)
        self.assertEqual(out["by_purpose"]["SUMMARY"]["output"], 30)
        self.assertEqual(set(out["by_model"]), {"a", "b"})

    def test_窗口外记录被排除(self):
        old = _entry(ts=NOW - 5 * 86400, day="2026-10-20")
        out1 = summarize([old], days=1, now=NOW)
        out7 = summarize([old], days=7, now=NOW)
        self.assertEqual(out1["window"]["calls"], 0)
        self.assertEqual(out7["window"]["calls"], 1)

    def test_预算按今日用量算(self):
        rows = [_entry(**{"in": 4000, "cached_in": 0, "out": 1000})]
        out = summarize(rows, days=1, budget=10000, now=NOW)
        self.assertEqual(out["budget"]["limit"], 10000)
        self.assertEqual(out["budget"]["used"], 5000)
        self.assertAlmostEqual(out["budget"]["ratio"], 0.5, places=4)
        self.assertEqual(out["budget"]["remaining"], 5000)

    def test_预算可以为零表示不设限(self):
        self.assertNotIn("budget", summarize([_entry()], days=1, budget=0, now=NOW))

    def test_媒体缓存命中率(self):
        rows = [
            _entry(purpose="media_digest", media_cached=True),
            _entry(purpose="media_digest", media_cached=False),
            _entry(purpose="media_digest", media_cached=True),
        ]
        w = summarize(rows, days=1, now=NOW)["window"]
        self.assertEqual(w["media_cache_total"], 3)
        self.assertEqual(w["media_cache_hits"], 2)
        self.assertAlmostEqual(w["media_cache_hit_ratio"], 2 / 3, places=4)

    def test_没有输入时命中率为零而不是报错(self):
        w = summarize([_entry(**{"in": 0, "cached_in": 0, "out": 0})], days=1, now=NOW)["window"]
        self.assertEqual(w["cache_hit_ratio"], 0.0)

    def test_脏输入不崩(self):
        self.assertEqual(summarize(None)["window"]["calls"], 0)
        self.assertEqual(summarize(["x", 1, None])["window"]["calls"], 0)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "usage_log.jsonl"
        self._patch = patch("core.usage._path", return_value=str(self.path))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_写入后能读回(self):
        record(None, purpose="GENERATION", model="m", input_other=1, input_cached=2, output=3)
        record(None, purpose="SUMMARY", model="m", input_other=4, input_cached=0, output=5)
        rows = load(None)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["purpose"], "GENERATION")
        self.assertEqual(rows[1]["in"], 4)

    def test_坏行被跳过(self):
        self.path.write_text('{"ok":1}\n不是 json\n\n{"day":"2099-01-01"}\n', encoding="utf-8")
        rows = load(None)
        self.assertEqual(len(rows), 1, "坏行与空行跳过；没有 day 的旧记录在按天裁剪时被丢弃")

    def test_文件不存在返回空(self):
        self.assertEqual(load(None), [])

    def test_写盘失败不影响调用方(self):
        with patch("core.usage._path", side_effect=OSError("盘满")):
            record(None, purpose="X")  # 不应该抛

    def test_collect_永不抛(self):
        self.path.write_text("坏了\n", encoding="utf-8")
        out = collect(None, days=1, budget=100)
        self.assertIn("window", out)

    def test_保留天数常量_合理(self):
        self.assertGreaterEqual(KEEP_DAYS, 7)


if __name__ == "__main__":
    unittest.main()
