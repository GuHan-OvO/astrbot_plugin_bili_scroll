"""收藏夹投喂池的离线测试（不请求真实接口）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.proactive import ProactiveMixin  # noqa: E402


class _Probe(ProactiveMixin):
    def __init__(self, config=None, payload=None):
        self.config = dict(config or {})
        self.payload = payload or {"code": 0, "data": {"medias": []}}
        self.calls = []

    async def _http_get(self, url, headers=None, params=None, **kwargs):
        self.calls.append({"url": url, "params": dict(params or {})})
        return self.payload, None


class ParseFavFolderTests(unittest.TestCase):
    def test_纯数字(self):
        self.assertEqual(ProactiveMixin._parse_fav_folders(["123", " 456 "]), ["123", "456"])

    def test_链接取fid(self):
        url = "https://space.bilibili.com/1/favlist?fid=98765&ftype=create"
        self.assertEqual(ProactiveMixin._parse_fav_folders([url]), ["98765"])

    def test_媒体id参数(self):
        self.assertEqual(
            ProactiveMixin._parse_fav_folders(["https://x/y?media_id=321"]), ["321"]
        )

    def test_去重与非法值(self):
        self.assertEqual(
            ProactiveMixin._parse_fav_folders(["1", "1", "", None, "abc"]), ["1"]
        )

    def test_空配置(self):
        self.assertEqual(ProactiveMixin._parse_fav_folders([]), [])
        self.assertEqual(ProactiveMixin._parse_fav_folders(None), [])


class FavPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_拉取并映射字段(self):
        payload = {
            "code": 0,
            "data": {
                "medias": [
                    {
                        "bvid": "BV1",
                        "title": "t1",
                        "intro": "i1",
                        "attr": 0,
                        "pubtime": 100,
                        "cover": "c1",
                        "upper": {"name": "up", "mid": 9},
                        "cnt_info": {"play": 12},
                    },
                    {"bvid": "BV2", "title": "t2", "attr": 9},
                    {"bvid": "", "title": "t3", "attr": 0},
                ]
            },
        }
        probe = _Probe({"PROACTIVE_FAV_FOLDERS": ["777"]}, payload)
        videos = await probe._get_fav_pool_videos()
        self.assertEqual([video["bvid"] for video in videos], ["BV1"])
        self.assertEqual(videos[0]["up_name"], "up")
        self.assertEqual(videos[0]["view"], 12)
        self.assertEqual(probe.calls[0]["params"]["media_id"], "777")

    async def test_没有配置不发请求(self):
        probe = _Probe({}, {"code": 0, "data": {"medias": []}})
        self.assertEqual(await probe._get_fav_pool_videos(), [])
        self.assertEqual(probe.calls, [])

    async def test_接口失败不抛(self):
        probe = _Probe({"PROACTIVE_FAV_FOLDERS": ["777"]}, {"code": -101, "data": None})
        self.assertEqual(await probe._get_fav_pool_videos(), [])

    async def test_多个收藏夹去重(self):
        payload = {
            "code": 0,
            "data": {"medias": [{"bvid": "BV9", "title": "t", "attr": 0}]},
        }
        probe = _Probe({"PROACTIVE_FAV_FOLDERS": ["1", "2"]}, payload)
        videos = await probe._get_fav_pool_videos()
        self.assertEqual([video["bvid"] for video in videos], ["BV9"])
        self.assertEqual(len(probe.calls), 2)


class QuotaTests(unittest.TestCase):
    def test_四源均分(self):
        quotas = ProactiveMixin._proactive_source_quotas(4)
        self.assertEqual(quotas, {"fav": 1, "follow": 1, "search": 1, "pool": 1})

    def test_余数先给收藏夹(self):
        quotas = ProactiveMixin._proactive_source_quotas(2)
        self.assertEqual(
            quotas, {"fav": 1, "follow": 1, "search": 0, "pool": 0}
        )

    def test_批次配额优先收藏夹(self):
        quotas = ProactiveMixin._proactive_batch_source_quotas(1)
        self.assertEqual(quotas["fav"], 1)

    def test_合并时收藏夹排最前(self):
        probe = _Probe({})
        candidates = {
            "fav": [{"bvid": "FAV1"}],
            "follow": [{"bvid": "F1"}],
            "search": [{"bvid": "S1"}],
            "pool": [{"bvid": "P1"}],
        }
        quotas = {"fav": 1, "follow": 0, "search": 0, "pool": 0}
        merged = probe._merge_proactive_source_candidates(candidates, quotas, 4)
        self.assertEqual(merged[0]["bvid"], "FAV1")
        self.assertEqual(len(merged), 4)

    def test_来源标签映射(self):
        self.assertEqual(ProactiveMixin._proactive_log_source("fav"), "fav")
        self.assertEqual(ProactiveMixin._proactive_log_source("following"), "follow")


if __name__ == "__main__":
    unittest.main()
