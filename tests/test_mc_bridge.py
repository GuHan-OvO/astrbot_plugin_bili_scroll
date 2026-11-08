"""memory_companion 写入桥的纯离线测试（不联网、不需要真的装记忆插件）。

覆盖三类约束：
1. 找桥：实例属性优先于模块级 getter（MC 关掉 private_companion_bridge.enabled 时
   get_active_bridge() 会返回 None，但 star_cls 上的 bridge 仍在）；
2. 写桥：payload 形状、幂等 memory_id、任何异常都不外抛；
3. 开关：LINK_COMPANION_INJECT_WATCH 单独决定写不写，不再连带 LINK_COMPANION_ENABLE。
"""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.mc_bridge import (  # noqa: E402
    MC_SESSION_ID,
    build_watch_memory_text,
    find_mc_bridge,
    remember_watch_entry,
)
from core.proactive import ProactiveMixin  # noqa: E402

ENTRY = {
    "time": "2026-11-08 12:00",
    "bvid": "BV1xx411c7mD",
    "title": "手搓一张桌子",
    "up_name": "木工老李",
    "up_mid": "12345",
    "tname": "生活",
    "score": 8,
    "comment": "榫卯做得干净",
    "review": "想再看一遍",
    "source": "following",
}


class _FakeBridge:
    """最小可用的 MemoryCompanionBridge 替身。"""

    def __init__(self, *, returns="mem_1", raises=None, active=True, can_write=True):
        self.calls = []
        self._returns = returns
        self._raises = raises
        self._active = active
        if not can_write:
            # None 不可调用：模拟「MC 版本过旧、没有 record_persona_life」
            self.record_persona_life = None

    async def record_persona_life(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        self.calls.append(kwargs)
        return self._returns

    def bridge_lifecycle_status(self):
        return {"active": self._active}


class _MCPlugin:
    def __init__(self, bridge):
        self.memory_companion = bridge


class _StarMeta:
    def __init__(self, name, star_obj=None, module=None, activated=True):
        self.name = name
        self.star_cls = star_obj
        self.module = module
        self.activated = activated


class _Ctx:
    def __init__(self, stars, raises=False):
        self._stars = stars
        self._raises = raises
        self.calls = 0

    def get_all_stars(self):
        self.calls += 1
        if self._raises:
            raise RuntimeError("枚举失败")
        return self._stars


class _AsyncCtx:
    def __init__(self, stars):
        self._stars = stars

    async def get_all_stars(self):
        return self._stars


class FindBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_按实例属性找到桥(self):
        bridge = _FakeBridge()
        ctx = _Ctx([_StarMeta("别的插件"), _StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))])
        self.assertIs(await find_mc_bridge(ctx), bridge)

    async def test_get_active_bridge失效时仍能从实例属性拿到(self):
        """MC 关掉 private_companion_bridge.enabled 时模块 getter 返回 None，实例仍在。"""
        bridge = _FakeBridge()
        module = types.ModuleType("astrbot_plugin_memory_companion.main")
        module.get_active_bridge = lambda: None
        module.get_memory_companion_bridge = lambda: None
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge), module)])
        self.assertIs(await find_mc_bridge(ctx), bridge)

    async def test_模块级getter可用时也能找到(self):
        bridge = _FakeBridge()
        module = types.ModuleType("fake_mc_main")
        module.get_active_bridge = lambda: bridge
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", None, module)])
        self.assertIs(await find_mc_bridge(ctx), bridge)

    async def test_未安装返回None(self):
        self.assertIsNone(await find_mc_bridge(_Ctx([_StarMeta("别的插件")])))

    async def test_未激活跳过(self):
        bridge = _FakeBridge()
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge), activated=False)])
        self.assertIsNone(await find_mc_bridge(ctx))

    async def test_生命周期已注销不认(self):
        bridge = _FakeBridge(active=False)
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))])
        self.assertIsNone(await find_mc_bridge(ctx))

    async def test_没有写入方法不认(self):
        bridge = _FakeBridge(can_write=False)
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))])
        self.assertIsNone(await find_mc_bridge(ctx))

    async def test_枚举抛错返回None(self):
        self.assertIsNone(await find_mc_bridge(_Ctx([], raises=True)))

    async def test_异步get_all_stars也能找到(self):
        bridge = _FakeBridge()
        ctx = _AsyncCtx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))])
        self.assertIs(await find_mc_bridge(ctx), bridge)

    async def test_命中缓存不重复枚举(self):
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(_FakeBridge()))])
        await find_mc_bridge(ctx)
        await find_mc_bridge(ctx)
        self.assertEqual(ctx.calls, 1, "30 秒内应走缓存，不要每轮都全量枚举")


class TextTests(unittest.TestCase):
    def test_没有标题就不写(self):
        self.assertEqual(build_watch_memory_text({"bvid": "BV1"}), "")

    def test_含标题评分与点评(self):
        text = build_watch_memory_text(ENTRY)
        self.assertIn("手搓一张桌子", text)
        self.assertIn("8/10", text)
        self.assertIn("榫卯做得干净", text)
        self.assertIn("生活区", text)


class RememberWatchTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, bridge=None, entry=None):
        ctx = _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge or _FakeBridge()))])
        return await remember_watch_entry(ctx, ENTRY if entry is None else entry), bridge

    async def test_写入成功(self):
        bridge = _FakeBridge()
        ok, _ = await self._run(bridge)
        self.assertTrue(ok)
        self.assertEqual(len(bridge.calls), 1)

    async def test_payload形状(self):
        bridge = _FakeBridge()
        await remember_watch_entry(
            _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))]), ENTRY
        )
        call = bridge.calls[0]
        self.assertEqual(call["scope"], "unknown", "scope=unknown → MC 不按会话归属过滤")
        self.assertEqual(call["session_id"], MC_SESSION_ID)
        self.assertEqual(call["source_plugin"], "astrbot_plugin_bili_scroll")
        self.assertEqual(call["memory_id"], "bilibot_watch_BV1xx411c7mD", "同视频固定 id，重复注入不堆条")
        self.assertIn("BV1xx411c7mD", call["tags"])
        self.assertEqual(call["metadata"]["bvid"], "BV1xx411c7mD")
        self.assertAlmostEqual(call["importance"], 0.70, places=2)

    async def test_没有桥返回False(self):
        ok = await remember_watch_entry(_Ctx([_StarMeta("别的插件")]), ENTRY)
        self.assertFalse(ok)

    async def test_写入抛异常不往外抛(self):
        bridge = _FakeBridge(raises=RuntimeError("boom"))
        ok, _ = await self._run(bridge)
        self.assertFalse(ok)

    async def test_返回空memory_id算失败(self):
        bridge = _FakeBridge(returns="")
        ok, _ = await self._run(bridge)
        self.assertFalse(ok)

    async def test_没有bvid不传memory_id(self):
        bridge = _FakeBridge()
        await remember_watch_entry(
            _Ctx([_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))]),
            {"title": "没 bvid 的视频"},
        )
        self.assertNotIn("memory_id", bridge.calls[0])


class InjectToggleTests(unittest.IsolatedAsyncioTestCase):
    """LINK_COMPANION_INJECT_WATCH 单独决定写不写。"""

    def _subject(self, config, stars=None):
        return types.SimpleNamespace(
            config=config,
            context=_Ctx(stars or []),
            _build_pc_watch_prompt=lambda entry: "prompt",
        )

    async def test_开关关闭不写(self):
        bridge = _FakeBridge()
        subject = self._subject(
            {"LINK_COMPANION_INJECT_WATCH": False, "LINK_COMPANION_ENABLE": True},
            [_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))],
        )
        self.assertFalse(await ProactiveMixin._inject_watch_into_companion(subject, ENTRY))
        self.assertEqual(bridge.calls, [], "开关关着就不该碰记忆")

    async def test_只开记忆开关也能写(self):
        """不再要求强联动总开关：记忆归属与「借她的通道说话」是两件事。"""
        bridge = _FakeBridge()
        subject = self._subject(
            {"LINK_COMPANION_INJECT_WATCH": True, "LINK_COMPANION_ENABLE": False},
            [_StarMeta("astrbot_plugin_memory_companion", _MCPlugin(bridge))],
        )
        self.assertTrue(await ProactiveMixin._inject_watch_into_companion(subject, ENTRY))
        self.assertEqual(len(bridge.calls), 1)

    async def test_没有记忆插件且强联动关闭时返回False(self):
        subject = self._subject(
            {"LINK_COMPANION_INJECT_WATCH": True, "LINK_COMPANION_ENABLE": False},
            [_StarMeta("别的插件")],
        )
        self.assertFalse(await ProactiveMixin._inject_watch_into_companion(subject, ENTRY))


if __name__ == "__main__":
    unittest.main()
