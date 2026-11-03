"""QQ ↔ B站 记忆互通回归（issue #1）。

主动刷视频/发动态写记忆时 `user_id="self"`（人格自己），而 QQ 侧注入按绑定的B站 UID
查询，两者对不上会导致 `get_recent_memories` 永远返回空、注入静默失效。

这里守住读取侧的契约：`include_self=True` 才把自我活动并进该用户的时间线，
默认仍只返回这人自己的记忆（其他人的对话不能顺带漏出来）。
"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.memory import MemoryMixin  # noqa: E402
from core.memory_api import BiliBotMemoryAPI  # noqa: E402


class _MemoryProbe(MemoryMixin):
    def __init__(self, memory):
        self._memory = memory


def _stamp(minutes_ago):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M")


def _video_memory(minutes_ago=30):
    return {
        "rpid": "proactive_watch_1",
        "thread_id": "proactive_watch",
        "user_id": "self",
        "time": _stamp(minutes_ago),
        "text": "Bot看了视频《手工皮具保姆级新手指南（工具篇）》评分 7.5/10",
        "source": "bilibili",
        "memory_type": "video",
        "level": "today",
        "importance": 6,
    }


def _owner_chat_memory(minutes_ago=20):
    return {
        "rpid": "chat_owner",
        "thread_id": "qq_private:10001",
        "user_id": "10001",
        "time": _stamp(minutes_ago),
        "text": "主人说今天想做皮具",
        "source": "qq_private",
        "memory_type": "chat",
        "level": "today",
        "importance": 5,
    }


def _stranger_chat_memory(minutes_ago=10):
    return {
        "rpid": "chat_stranger",
        "thread_id": "qq_private:20002",
        "user_id": "20002",
        "time": _stamp(minutes_ago),
        "text": "别人说了一句不该被主人看到的话",
        "source": "qq_private",
        "memory_type": "chat",
        "level": "today",
        "importance": 5,
    }


class RecentMemoriesIncludeSelfTests(unittest.TestCase):
    def _api(self, memories):
        return BiliBotMemoryAPI(_MemoryProbe(memories))

    def _texts(self, results):
        return [item["text"] for item in results]

    def test_默认只返回该用户自己的记忆(self):
        api = self._api([_video_memory(), _owner_chat_memory(), _stranger_chat_memory()])
        results = api.get_recent_memories(user_id="10001", hours=24 * 7, limit=12, reader_scope="admin")
        texts = self._texts(results)
        self.assertIn("主人说今天想做皮具", "\n".join(texts))
        self.assertNotIn("手工皮具", "\n".join(texts))

    def test_include_self并入人格自己的B站活动(self):
        api = self._api([_video_memory(), _owner_chat_memory(), _stranger_chat_memory()])
        results = api.get_recent_memories(
            user_id="10001", hours=24 * 7, limit=12, reader_scope="admin", include_self=True
        )
        joined = "\n".join(self._texts(results))
        self.assertIn("手工皮具", joined)
        self.assertIn("主人说今天想做皮具", joined)

    def test_include_self不会带出其他用户的对话(self):
        api = self._api([_video_memory(), _owner_chat_memory(), _stranger_chat_memory()])
        results = api.get_recent_memories(
            user_id="10001", hours=24 * 7, limit=12, reader_scope="admin", include_self=True
        )
        joined = "\n".join(self._texts(results))
        self.assertNotIn("不该被主人看到", joined)

    def test_过期的自我活动仍会被时间窗挡住(self):
        old_video = _video_memory(minutes_ago=60 * 24 * 10)  # 10 天前
        api = self._api([old_video, _owner_chat_memory()])
        results = api.get_recent_memories(
            user_id="10001", hours=24 * 7, limit=12, reader_scope="admin", include_self=True
        )
        joined = "\n".join(self._texts(results))
        self.assertNotIn("手工皮具", joined)


if __name__ == "__main__":
    unittest.main()
