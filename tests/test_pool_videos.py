"""视频池取数 ``_get_pool_videos`` 的返回值回归测试。

2026-11-07 线上报错（实例 2bcad40e）：

    for video in pool_videos
    TypeError: 'NoneType' object is not iterable

根因：v2.0.0（``75b0266``）在 ``_get_pool_videos`` 和它的下一条语句之间插入了
``_apply_pool_weights``，使上游原有的 ``return all_videos`` 被挤进新方法顶部，
变成不可达语句；``_get_pool_videos`` 因此恒返回 ``None``。``trial.py`` 用
``isinstance(videos, list)`` 兜住了，试运行只表现为「候选 0」，线上主动看片则直接崩。

这里锁住的是**返回值契约**：无论是取到数据、取不到数据，还是池配置非法，
都必须返回 ``list``；另外用 AST 锁住「取数函数里存在带值的 return」，防止同类回归。
"""

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.proactive import ProactiveMixin  # noqa: E402


def _video(bvid):
    return {"bvid": bvid, "title": bvid, "desc": "", "up_name": "UP", "up_mid": 1,
            "pubdate": 0, "pic": "", "view": 1, "tname": ""}


class _PoolProbe(ProactiveMixin):
    def __init__(self, config=None, hot=None, weekly=None):
        self.config = dict(config or {})
        self._hot = list(hot or [])
        self._weekly = list(weekly or [])
        self.hot_calls = 0
        self.weekly_calls = 0

    async def _get_hot_videos(self, min_pubdate=0):
        self.hot_calls += 1
        return [dict(video) for video in self._hot]

    async def _get_weekly_videos(self):
        self.weekly_calls += 1
        return [dict(video) for video in self._weekly]


class PoolVideosReturnTests(unittest.IsolatedAsyncioTestCase):
    async def test_默认热门池返回列表(self):
        probe = _PoolProbe({"PROACTIVE_VIDEO_POOLS": ["popular"]},
                           hot=[_video("BV1"), _video("BV2")])
        videos = await probe._get_pool_videos()

        self.assertIsInstance(videos, list)
        self.assertEqual([video["bvid"] for video in videos], ["BV1", "BV2"])

    async def test_取不到视频返回空列表而不是None(self):
        probe = _PoolProbe({"PROACTIVE_VIDEO_POOLS": ["popular"]}, hot=[])
        videos = await probe._get_pool_videos()

        self.assertIsInstance(videos, list)
        self.assertEqual(videos, [])
        self.assertEqual(probe.hot_calls, 1)

    async def test_未知池名返回空列表(self):
        probe = _PoolProbe({"PROACTIVE_VIDEO_POOLS": ["这不是一个池"]})
        videos = await probe._get_pool_videos()

        self.assertIsInstance(videos, list)
        self.assertEqual(videos, [])

    async def test_多池配权重仍返回列表(self):
        probe = _PoolProbe(
            {"PROACTIVE_VIDEO_POOLS": ["popular", "weekly"],
             "PROACTIVE_POOL_WEIGHTS": ["popular:2", "weekly:1"]},
            hot=[_video("BV1"), _video("BV2")],
            weekly=[_video("BV3")],
        )
        videos = await probe._get_pool_videos()

        self.assertIsInstance(videos, list)
        self.assertTrue(videos)
        self.assertTrue(all(isinstance(video, dict) for video in videos))

    async def test_重复bvid去重后仍为列表(self):
        probe = _PoolProbe({"PROACTIVE_VIDEO_POOLS": ["popular"]},
                           hot=[_video("BV1"), _video("BV1")])
        videos = await probe._get_pool_videos()

        self.assertIsInstance(videos, list)
        self.assertEqual(len(videos), 1)


class PoolVideosAstContractTests(unittest.TestCase):
    """静态锁：取数函数必须存在带值的 return，且不允许出现不可达 return。"""

    def test_取数函数有带值return(self):
        tree = ast.parse((_ROOT / "core" / "proactive.py").read_text(encoding="utf-8"))
        func = next(
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_get_pool_videos"
        )
        returned = [node for node in ast.walk(func)
                    if isinstance(node, ast.Return) and node.value is not None]
        self.assertTrue(returned, "_get_pool_videos 缺少 return，会把 None 传给遍历它的调用方")

    def test_池权重方法没有不可达语句(self):
        tree = ast.parse((_ROOT / "core" / "proactive.py").read_text(encoding="utf-8"))
        func = next(
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_apply_pool_weights"
        )
        for index, node in enumerate(func.body):
            if isinstance(node, (ast.Return, ast.Raise)):
                self.assertEqual(
                    index, len(func.body) - 1,
                    f"_apply_pool_weights 第 {node.lineno} 行的 return 之后还有不可达语句",
                )


if __name__ == "__main__":
    unittest.main()
