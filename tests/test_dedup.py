"""候选去重的纯离线测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.dedup import (  # noqa: E402
    DEFAULT_TITLE_THRESHOLD,
    dedupe_by_bvid,
    dedupe_similar_titles,
    title_similarity,
)


class SimilarityTests(unittest.TestCase):
    def test_相同标题为1(self):
        self.assertEqual(title_similarity("原神新版本前瞻", "原神新版本前瞻"), 1.0)

    def test_完全不同为0(self):
        self.assertEqual(title_similarity("原神新版本前瞻", "战斧牛排评测"), 0.0)

    def test_同一事件不同措辞较高但不是1(self):
        score = title_similarity("原神 5.3 版本前瞻直播", "原神5.3版本前瞻全解析")
        self.assertGreater(score, 0.5)
        self.assertLess(score, 1.0)

    def test_空输入返回0(self):
        for a, b in (("", "x"), ("x", ""), (None, "x"), ("", "")):
            self.assertEqual(title_similarity(a, b), 0.0)

    def test_忽略标点与空白(self):
        self.assertEqual(title_similarity("原神 新版本，前瞻！", "原神新版本前瞻"), 1.0)


class DedupeByBvidTests(unittest.TestCase):
    def test_同BV只留播放高的(self):
        rows = [
            {"bvid": "BV1", "title": "A", "play": 100},
            {"bvid": "BV2", "title": "B", "play": 50},
            {"bvid": "BV1", "title": "A", "play": 900},
        ]
        out = dedupe_by_bvid(rows)
        self.assertEqual([r["bvid"] for r in out], ["BV1", "BV2"])
        self.assertEqual(out[0]["play"], 900, "应保留播放量更高的那份")

    def test_保持首次出现的位置(self):
        rows = [
            {"bvid": "BV1", "play": 1},
            {"bvid": "BV2", "play": 2},
            {"bvid": "BV1", "play": 99},
            {"bvid": "BV3", "play": 3},
        ]
        self.assertEqual([r["bvid"] for r in dedupe_by_bvid(rows)], ["BV1", "BV2", "BV3"])

    def test_没有BV的条目原样保留(self):
        rows = [{"title": "无号"}, {"bvid": "BV1"}]
        self.assertEqual(len(dedupe_by_bvid(rows)), 2)

    def test_脏输入不崩(self):
        for bad in (None, "x", 0, [None, "x", 1]):
            self.assertEqual(dedupe_by_bvid(bad), [])


class DedupeTitleTests(unittest.TestCase):
    def test_相似标题只留最热的一条(self):
        rows = [
            {"bvid": "BV1", "title": "原神 5.3 版本前瞻直播", "play": 100},
            {"bvid": "BV2", "title": "原神5.3版本前瞻全解析", "play": 5000},
            {"bvid": "BV3", "title": "战斧牛排评测", "play": 200},
        ]
        # 这对标题的 2-gram Jaccard ≈ 0.58，所以用 0.5 的阈值才该合并；
        # 默认 0.75 是刻意保守（宁可漏合并，也不把不同视角删成一条）。
        out = dedupe_similar_titles(rows, threshold=0.5)
        bvids = [r["bvid"] for r in out]
        self.assertIn("BV2", bvids)
        self.assertNotIn("BV1", bvids)
        self.assertIn("BV3", bvids, "不相似的不能误删")
        # 默认阈值下这两条不该被合并
        self.assertEqual(len(dedupe_similar_titles(rows[:2])), 2)

    def test_阈值可调(self):
        rows = [
            {"bvid": "BV1", "title": "原神 5.3 版本前瞻直播", "play": 100},
            {"bvid": "BV2", "title": "原神5.3版本前瞻全解析", "play": 5000},
        ]
        self.assertEqual(len(dedupe_similar_titles(rows, threshold=1.01)), 2)
        self.assertEqual(len(dedupe_similar_titles(rows, threshold=0.3)), 1)

    def test_结果与输入顺序无关(self):
        a = {"bvid": "BV1", "title": "原神 5.3 版本前瞻直播", "play": 100}
        b = {"bvid": "BV2", "title": "原神5.3版本前瞻全解析", "play": 5000}
        forward = [r["bvid"] for r in dedupe_similar_titles([a, b])]
        backward = [r["bvid"] for r in dedupe_similar_titles([b, a])]
        self.assertEqual(set(forward), set(backward))

    def test_默认阈值偏保守(self):
        self.assertGreaterEqual(DEFAULT_TITLE_THRESHOLD, 0.7)

    def test_单条与空输入(self):
        self.assertEqual(len(dedupe_similar_titles([{"bvid": "BV1", "title": "x"}])), 1)
        self.assertEqual(dedupe_similar_titles(None), [])


if __name__ == "__main__":
    unittest.main()
