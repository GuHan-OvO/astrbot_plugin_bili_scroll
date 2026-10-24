"""历史查询的纯离线测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.history import (  # noqa: E402
    MAX_LIMIT,
    find_entry,
    is_failed,
    is_recommended,
    query_history,
    summarize,
)


def _entry(**over):
    base = {
        "time": "2026-10-22 18:51",
        "bvid": "BV1xx411c7mD",
        "title": "标题",
        "up_name": "UP",
        "score": 8.0,
        "score_reason": "讲得清楚",
        "mood": "开心",
        "comment": "评论",
        "review": "感想",
        "pic": "https://i0.hdslb.com/a.jpg",
        "tname": "科技",
        "source": "search",
        "actions": [],
    }
    base.update(over)
    return base


class RecommendFlagTests(unittest.TestCase):
    def test_三种渠道任一都算推荐过(self):
        for action in ("📢评论区推荐给主人", "✉️私信推荐给主人", "💬QQ推荐给主人"):
            self.assertTrue(is_recommended(_entry(actions=[action])), action)

    def test_只有普通评论不算推荐(self):
        self.assertFalse(is_recommended(_entry(actions=["💬评论"])))

    def test_actions不是列表时不算(self):
        self.assertFalse(is_recommended(_entry(actions=None)))
        self.assertFalse(is_recommended(_entry(actions="📢评论区推荐给主人")))

    def test_失败条目识别(self):
        self.assertTrue(is_failed(_entry(evaluation_status="failed")))
        self.assertFalse(is_failed(_entry()))


class QueryTests(unittest.TestCase):
    def setUp(self):
        self._rows = [
            _entry(time="2026-10-20 10:00", bvid="BV1", score=9.0, mood="开心", source="search"),
            _entry(time="2026-10-22 18:51", bvid="BV2", score=6.0, mood="平静", source="follow",
                   actions=["📢评论区推荐给主人"]),
            _entry(time="2026-10-21 12:00", bvid="BV3", score=3.0, mood="无聊", source="pool",
                   evaluation_status="failed"),
        ]

    def test_按时间倒序且分页(self):
        out = query_history(self._rows, limit=2)
        self.assertEqual(out["total"], 3)
        self.assertEqual([i["bvid"] for i in out["items"]], ["BV2", "BV3"])
        page2 = query_history(self._rows, limit=2, offset=2)
        self.assertEqual([i["bvid"] for i in page2["items"]], ["BV1"])

    def test_offset负数归零(self):
        self.assertEqual(query_history(self._rows, offset=-5)["offset"], 0)

    def test_limit上限(self):
        self.assertEqual(query_history(self._rows, limit=9999)["limit"], MAX_LIMIT)
        self.assertEqual(query_history(self._rows, limit=0)["limit"], 1)

    def test_分数区间(self):
        out = query_history(self._rows, min_score=6, max_score=8.5)
        self.assertEqual([i["bvid"] for i in out["items"]], ["BV2"])
        # 边界要闭区间：9 分也在 [6, 9] 内
        self.assertEqual(query_history(self._rows, min_score=6, max_score=9)["total"], 2)

    def test_分数缺失的条目在区间过滤时被排除(self):
        rows = [_entry(bvid="BVX", score=None)]
        self.assertEqual(query_history(rows, min_score=1)["total"], 0)

    def test_心情与来源过滤(self):
        self.assertEqual(query_history(self._rows, mood="开心")["items"][0]["bvid"], "BV1")
        self.assertEqual(query_history(self._rows, source="follow")["items"][0]["bvid"], "BV2")
        self.assertEqual(query_history(self._rows, source="FOLLOW")["total"], 1, "来源不区分大小写")

    def test_推荐过与失败过滤(self):
        self.assertEqual(query_history(self._rows, recommended=True)["total"], 1)
        self.assertEqual(query_history(self._rows, recommended=False)["total"], 2)
        self.assertEqual(query_history(self._rows, failed=True)["items"][0]["bvid"], "BV3")
        self.assertEqual(query_history(self._rows, failed=False)["total"], 2)

    def test_关键词匹配标题与理由(self):
        self.assertEqual(query_history(self._rows, q="标题")["total"], 3)
        self.assertEqual(query_history(self._rows, q="讲得清楚")["total"], 3)
        self.assertEqual(query_history(self._rows, q="不存在的词")["total"], 0)

    def test_时间区间(self):
        out = query_history(self._rows, since="2026-10-21", until="2026-10-21 23:59")
        self.assertEqual([i["bvid"] for i in out["items"]], ["BV3"])

    def test_脏输入不崩(self):
        for bad in (None, "x", 0, [None, "x", 1]):
            self.assertEqual(query_history(bad)["total"], 0)

    def test_列表条目含recommended与failed标志且分数是数字(self):
        out = query_history(self._rows, limit=3)
        by_bvid = {i["bvid"]: i for i in out["items"]}
        self.assertTrue(by_bvid["BV2"]["recommended"])
        self.assertTrue(by_bvid["BV3"]["failed"])
        self.assertIsInstance(by_bvid["BV1"]["score"], float)
        self.assertNotIn("preference_signals", by_bvid["BV1"], "长字段不该进列表")


class StatsTests(unittest.TestCase):
    def test_统计口径(self):
        rows = [
            _entry(time="2026-10-24 08:00", score=8.0, actions=["📢评论区推荐给主人"]),
            _entry(time="2026-10-24 09:00", score=6.0),
            _entry(time="2026-10-20 09:00", score=0, evaluation_status="failed"),
        ]
        stats = summarize(rows, today_prefix="2026-10-24")
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["today"], 2)
        self.assertEqual(stats["recommended"], 1)
        self.assertEqual(stats["failed"], 1)
        # 平均分不把 0 分的失败条目算进去
        self.assertEqual(stats["average_score"], 7.0)

    def test_空列表(self):
        stats = summarize([])
        self.assertEqual(stats["average_score"], 0.0)
        self.assertEqual(stats["total"], 0)


class FindEntryTests(unittest.TestCase):
    def test_取最新一条(self):
        rows = [
            _entry(bvid="BV9", time="2026-10-20 10:00", score=5),
            _entry(bvid="BV9", time="2026-10-22 10:00", score=9, actions=["✉️私信推荐给主人"]),
        ]
        hit = find_entry(rows, "BV9")
        self.assertEqual(hit["score"], 9.0)
        self.assertTrue(hit["recommended"])
        self.assertEqual(hit["seen_times"], 2)

    def test_找不到或空BV(self):
        self.assertIsNone(find_entry([_entry()], "BV0"))
        self.assertIsNone(find_entry([_entry()], ""))


if __name__ == "__main__":
    unittest.main()
