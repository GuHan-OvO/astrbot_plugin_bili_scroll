"""watch_log 按月归档的离线测试（真实临时文件，不碰实例数据）。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core import watch_log  # noqa: E402


class _DiskPlugin:
    """真实读写临时目录，复刻 UtilsMixin 的两个持久化方法。"""

    def __init__(self, fail_archive=False, config=None):
        self.fail_archive = fail_archive
        self.config = dict(config or {})

    def _load_json(self, path, default=None):
        try:
            with open(path, encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return [] if default is None else default

    def _save_json(self, path, data):
        if self.fail_archive and watch_log.ARCHIVE_DIRNAME in str(path):
            raise OSError("磁盘满")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False)


def _entry(time_text, bvid, title="t"):
    return {"time": time_text, "bvid": bvid, "title": title}


class WatchLogArchiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.active = str(self.root / "watch_log.json")
        self.archive = self.root / "watch_log_archive"
        self._patches = [
            patch.object(watch_log, "WATCH_LOG_FILE", self.active),
            patch.object(watch_log, "archive_dir", lambda: str(self.archive)),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in reversed(self._patches):
            item.stop()
        self._tmp.cleanup()

    def test_未超上限不归档(self):
        plugin = _DiskPlugin()
        for i in range(3):
            watch_log.append_watch_entry(plugin, _entry(f"2026-10-0{i + 1} 10:00", f"BV{i}"), cap=3)
        self.assertFalse(self.archive.exists())
        self.assertEqual(len(plugin._load_json(self.active, [])), 3)

    def test_超出上限按月归档(self):
        plugin = _DiskPlugin()
        watch_log.append_watch_entry(plugin, _entry("2026-08-31 23:00", "BV0"), cap=2)
        watch_log.append_watch_entry(plugin, _entry("2026-09-01 10:00", "BV1"), cap=2)
        watch_log.append_watch_entry(plugin, _entry("2026-09-02 10:00", "BV2"), cap=2)
        watch_log.append_watch_entry(plugin, _entry("2026-09-03 10:00", "BV3"), cap=2)

        self.assertEqual(len(plugin._load_json(self.active, [])), 2)
        august = plugin._load_json(os.path.join(self.archive, "2026-08.json"), [])
        self.assertEqual([item["bvid"] for item in august], ["BV0"])
        september = plugin._load_json(os.path.join(self.archive, "2026-09.json"), [])
        self.assertEqual([item["bvid"] for item in september], ["BV1"])

    def test_全量读取合并归档并按时间升序(self):
        plugin = _DiskPlugin()
        for time_text, bvid in (
            ("2026-08-15 10:00", "BV0"),
            ("2026-09-15 10:00", "BV1"),
            ("2026-10-15 10:00", "BV2"),
        ):
            watch_log.append_watch_entry(plugin, _entry(time_text, bvid), cap=1)

        rows = watch_log.load_watch_entries(plugin)
        self.assertEqual([item["bvid"] for item in rows], ["BV0", "BV1", "BV2"])
        self.assertEqual(watch_log.watch_entry_count(plugin), 3)

    def test_同一时间与bvid只留最新一份(self):
        plugin = _DiskPlugin()
        self.archive.mkdir(parents=True)
        old = {"time": "2026-10-01 10:00", "bvid": "BV1", "actions": []}
        new = {"time": "2026-10-01 10:00", "bvid": "BV1", "actions": ["👍点赞"]}
        plugin._save_json(str(self.archive / "2026-10.json"), [old])
        plugin._save_json(self.active, [new])

        rows = watch_log.load_watch_entries(plugin)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actions"], ["👍点赞"])

    def test_归档写入幂等(self):
        plugin = _DiskPlugin()
        watch_log.append_watch_entry(plugin, _entry("2026-10-01 10:00", "BV1"), cap=1)
        watch_log.append_watch_entry(plugin, _entry("2026-10-02 10:00", "BV2"), cap=1)
        # 人为重复写同一条，模拟异常重试或手工恢复
        watch_log._archive_entries(plugin, [_entry("2026-10-01 10:00", "BV1")])
        archived = plugin._load_json(str(self.archive / "2026-10.json"), [])
        self.assertEqual([row["bvid"] for row in archived], ["BV1"])

    def test_配置的cap被读取(self):
        plugin = _DiskPlugin(config={"WATCH_LOG_ACTIVE_CAP": 2})
        for i in range(3):
            watch_log.append_watch_entry(
                plugin, _entry(f"2026-10-0{i + 1} 10:00", f"BV{i}")
            )
        self.assertEqual(len(plugin._load_json(self.active, [])), 2)
        self.assertTrue(self.archive.exists())

    def test_按bvid更新主文件(self):
        plugin = _DiskPlugin()
        watch_log.append_watch_entry(plugin, _entry("2026-10-01 10:00", "BV1"), cap=10)
        self.assertTrue(watch_log.update_watch_entry(plugin, "BV1", {"actions": ["💬评论"]}))
        self.assertEqual(plugin._load_json(self.active, [])[0]["actions"], ["💬评论"])

    def test_按bvid更新归档(self):
        plugin = _DiskPlugin()
        watch_log.append_watch_entry(plugin, _entry("2026-10-01 10:00", "BV1"), cap=1)
        watch_log.append_watch_entry(plugin, _entry("2026-10-02 10:00", "BV2"), cap=1)

        self.assertTrue(watch_log.update_watch_entry(plugin, "BV1", {"recommended_at": "x"}))
        archived = plugin._load_json(str(self.archive / "2026-10.json"), [])
        self.assertEqual(archived[0]["recommended_at"], "x")

    def test_更新不存在的bvid返回False(self):
        plugin = _DiskPlugin()
        self.assertFalse(watch_log.update_watch_entry(plugin, "BVnope", {"actions": []}))

    def test_归档失败时不裁剪主文件(self):
        plugin = _DiskPlugin(fail_archive=True)
        for i in range(3):
            watch_log.append_watch_entry(plugin, _entry(f"2026-10-0{i + 1} 10:00", f"BV{i}"), cap=2)
        self.assertEqual(len(plugin._load_json(self.active, [])), 3, "归档失败也不能丢记录")

    def test_月份解析异常归到unknown(self):
        self.assertEqual(watch_log.entry_month({"time": "2026-10-01 10:00"}), "2026-10")
        self.assertEqual(watch_log.entry_month({"time": ""}), "unknown")
        self.assertEqual(watch_log.entry_month({"time": "bad"}), "unknown")
        self.assertEqual(watch_log.entry_month(None), "unknown")


if __name__ == "__main__":
    unittest.main()
