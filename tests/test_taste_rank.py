"""候选排序的离线测试：打分、稳定排序、降级。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.taste_rank import (  # noqa: E402
    EXPLORATION_FLOOR,
    PENALTY_DISLIKE,
    WEIGHT_INTEREST,
    WEIGHT_PARTITION,
    build_index,
    rank_candidates,
    score_video,
)


class _FakePlugin:
    def __init__(self, *, tids=(), tname_map=None, lifecycle=None, config=None, broken=False):
        self.config = config if config is not None else {}
        self._tids = list(tids)
        self._tname_map = tname_map or {"单机游戏": 17, "生活": 160}
        self._lifecycle = list(lifecycle or [])
        self._broken = broken

    def _get_taste_tids(self):
        if self._broken:
            raise RuntimeError("口味读取失败")
        return self._tids

    def _build_tname_to_tid_map(self):
        if self._broken:
            raise RuntimeError("分区表读取失败")
        return self._tname_map

    def _lifecycle_preference_items(self):
        return self._lifecycle


class BuildIndexTests(unittest.TestCase):
    def test_正常收集口味分区与负向信号(self):
        plugin = _FakePlugin(
            tids=[17],
            lifecycle=[
                {"polarity": "dislike", "value": "标题党"},
                {"polarity": "like", "value": "木工"},
            ],
        )
        index = build_index(plugin)
        self.assertEqual(index["tids"], {17})
        self.assertIn("标题党", index["negative"])
        self.assertNotIn("木工", index["negative"], "正向信号不该进负向集合")

    def test_读取失败时降级为空集合(self):
        index = build_index(_FakePlugin(broken=True))
        self.assertEqual(index["tids"], set())
        self.assertEqual(index["tname_to_tid"], {})
        self.assertEqual(index["negative"], set())


class ScoreTests(unittest.TestCase):
    def _index(self, **kwargs):
        return {
            "tids": kwargs.get("tids", {17}),
            "tname_to_tid": kwargs.get("tname_to_tid", {"单机游戏": 17}),
            "interests": kwargs.get("interests", []),
            "negative": kwargs.get("negative", set()),
        }

    def test_分区命中加分(self):
        score, reason = score_video({"tname": "单机游戏"}, self._index())
        self.assertAlmostEqual(score, WEIGHT_PARTITION)
        self.assertIn("分区", reason)

    def test_分区不在口味里不加分(self):
        score, _ = score_video({"tname": "舞蹈"}, self._index())
        self.assertEqual(score, 0.0)

    def test_画像题材命中标题(self):
        index = self._index(interests=["独立游戏", "木工"])
        score, reason = score_video({"title": "一款独立游戏开发幕后"}, index)
        self.assertAlmostEqual(score, WEIGHT_INTEREST)
        self.assertIn("独立游戏", reason)

    def test_负向题材扣分(self):
        index = self._index(negative={"标题党"})
        score, reason = score_video({"title": "标题党大赏"}, index)
        self.assertLess(score, 0)
        self.assertAlmostEqual(score, -PENALTY_DISLIKE)
        self.assertIn("避开", reason)

    def test_无命中返回零分且无理由(self):
        score, reason = score_video({"title": "毫不相关", "tname": "舞蹈"}, self._index())
        self.assertEqual(score, 0.0)
        self.assertEqual(reason, "")


class RankTests(unittest.TestCase):
    def _index(self):
        return {
            "tids": {17},
            "tname_to_tid": {"单机游戏": 17},
            "interests": [],
            "negative": set(),
        }

    def test_fav保持原顺序(self):
        fav = [{"bvid": "BV1", "tname": "舞蹈"}, {"bvid": "BV2", "tname": "单机游戏"}]
        ranked = rank_candidates({"fav": fav}, self._index(), exploration_ratio=0.0)
        self.assertEqual([item["bvid"] for item in ranked["fav"]], ["BV1", "BV2"])

    def test_命中口味的候选排到前面(self):
        items = [
            {"bvid": "BVlow", "tname": "舞蹈"},
            {"bvid": "BVhigh", "tname": "单机游戏"},
        ]
        ranked = rank_candidates({"pool": items}, self._index(), exploration_ratio=0.0)
        self.assertEqual([item["bvid"] for item in ranked["pool"]], ["BVhigh", "BVlow"])
        self.assertIn("分区", ranked["pool"][0]["_rank_reason"])

    def test_同分保持原相对顺序(self):
        items = [{"bvid": "BV1", "tname": "舞蹈"}, {"bvid": "BV2", "tname": "舞蹈"}]
        ranked = rank_candidates({"pool": items}, self._index(), exploration_ratio=0.0)
        self.assertEqual([item["bvid"] for item in ranked["pool"]], ["BV1", "BV2"])

    def test_探索位有分数下限(self):
        # ratio=1.0 时所有候选都算探索位，负分也会被抬到下限
        items = [{"bvid": "BVneg", "title": "标题党大赏"}]
        index = self._index()
        index["negative"] = {"标题党"}
        ranked = rank_candidates({"pool": items}, index, exploration_ratio=1.0)
        video = ranked["pool"][0]
        self.assertTrue(video.get("_exploration"))
        self.assertGreaterEqual(score_video(video, index)[0], -PENALTY_DISLIKE)
        self.assertEqual(EXPLORATION_FLOOR, 0.15)

    def test_空输入不抛错(self):
        ranked = rank_candidates({"pool": []}, self._index())
        self.assertEqual(ranked["pool"], [])


if __name__ == "__main__":
    unittest.main()
