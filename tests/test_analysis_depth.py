"""档位预设的纯离线测试。

重点守一件事：**`standard` 档必须逐项等于原版硬编码值**，
否则「升级后什么都不变」就不成立。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.analysis_depth import (  # noqa: E402
    CUSTOM_DEPTH,
    DEFAULT_DEPTH,
    DEPTH_PRESETS,
    frames_per_segment,
    resolve,
    result_chars,
    subtitle_chars,
    visual_policy,
)


class PresetTests(unittest.TestCase):
    def test_默认档就是standard(self):
        self.assertEqual(DEFAULT_DEPTH, "standard")

    def test_standard等于原版硬编码值(self):
        # 这些数字来自改造前的代码：字幕 1500、结果 1600、分段 10、帧 8、预算 50000
        p = DEPTH_PRESETS["standard"]
        self.assertEqual(p["subtitle_chars"], 1500)
        self.assertEqual(p["result_chars"], 1600)
        self.assertEqual(p["segment_max_count"], 10)
        self.assertEqual(p["max_frames"], 8)
        self.assertEqual(p["token_budget_daily"], 50000)
        self.assertEqual(p["visual_policy"], "when_text_insufficient")

    def test_各档齐全且字段一致(self):
        expected = {
            "visual_policy", "segment_max_count", "max_frames", "frames_per_segment",
            "token_budget_daily", "subtitle_chars", "result_chars",
        }
        for name in ("subtitle_only", "lean", "standard", "deep", "unlimited"):
            self.assertIn(name, DEPTH_PRESETS)
            self.assertEqual(set(DEPTH_PRESETS[name]), expected, name)

    def test_无限制档每项都不低且一定看画面(self):
        top = DEPTH_PRESETS["unlimited"]
        deep = DEPTH_PRESETS["deep"]
        std = DEPTH_PRESETS["standard"]
        self.assertEqual(top["visual_policy"], "always")
        self.assertGreater(top["segment_max_count"], deep["segment_max_count"])
        self.assertGreaterEqual(top["frames_per_segment"], deep["frames_per_segment"])
        self.assertGreater(top["token_budget_daily"], deep["token_budget_daily"])
        self.assertGreater(top["subtitle_chars"], deep["subtitle_chars"])
        self.assertGreater(top["result_chars"], deep["result_chars"])
        # 不能靠调参悄悄退回标准档的覆盖
        self.assertGreater(top["frames_per_segment"], std["frames_per_segment"])

    def test_只看字幕档永不做视觉(self):
        self.assertEqual(DEPTH_PRESETS["subtitle_only"]["visual_policy"], "never")

    def test_看更细档更贵更细(self):
        deep = DEPTH_PRESETS["deep"]
        std = DEPTH_PRESETS["standard"]
        self.assertEqual(deep["visual_policy"], "always")
        self.assertGreater(deep["subtitle_chars"], std["subtitle_chars"])
        self.assertGreater(deep["token_budget_daily"], std["token_budget_daily"])
        self.assertGreater(deep["segment_max_count"], std["segment_max_count"])

    def test_省token档更省(self):
        lean = DEPTH_PRESETS["lean"]
        std = DEPTH_PRESETS["standard"]
        self.assertLessEqual(lean["token_budget_daily"], std["token_budget_daily"])
        self.assertLessEqual(lean["segment_max_count"], std["segment_max_count"])


class ResolveTests(unittest.TestCase):
    def test_未配置时走standard(self):
        self.assertEqual(resolve({})["depth"], "standard")
        self.assertEqual(resolve({})["subtitle_chars"], 1500)

    def test_非custom档忽略单项配置(self):
        cfg = {
            "ANALYSIS_DEPTH": "lean",
            "ANALYSIS_SUBTITLE_CHARS": 9000,  # 应被忽略
            "VIDEO_VISUAL_ANALYSIS_POLICY": "always",  # 应被忽略
        }
        out = resolve(cfg)
        self.assertEqual(out["depth"], "lean")
        self.assertEqual(out["subtitle_chars"], DEPTH_PRESETS["lean"]["subtitle_chars"])
        self.assertEqual(out["visual_policy"], DEPTH_PRESETS["lean"]["visual_policy"])

    def test_custom档读单项(self):
        cfg = {
            "ANALYSIS_DEPTH": CUSTOM_DEPTH,
            "ANALYSIS_SUBTITLE_CHARS": 4321,
            "ANALYSIS_RESULT_CHARS": 2222,
            "MEDIA_MAX_FRAMES": 3,
            "MEDIA_TOKEN_BUDGET_DAILY": 70000,
            "VIDEO_SEGMENT_MAX_COUNT": 4,
            "VIDEO_VISUAL_ANALYSIS_POLICY": "always",
        }
        out = resolve(cfg)
        self.assertEqual(out["depth"], "custom")
        self.assertEqual(out["subtitle_chars"], 4321)
        self.assertEqual(out["result_chars"], 2222)
        self.assertEqual(out["max_frames"], 3)
        self.assertEqual(out["frames_per_segment"], 3, "自定义档每段帧数应跟随 MEDIA_MAX_FRAMES")
        self.assertEqual(out["token_budget_daily"], 70000)
        self.assertEqual(out["segment_max_count"], 4)
        self.assertEqual(out["visual_policy"], "always")

    def test_custom档缺项时用默认(self):
        out = resolve({"ANALYSIS_DEPTH": "custom"})
        self.assertEqual(out["subtitle_chars"], 1500)
        self.assertEqual(out["result_chars"], 1600)

    def test_未知档回退standard(self):
        out = resolve({"ANALYSIS_DEPTH": "ultra"})
        self.assertEqual(out["depth"], "standard")
        self.assertEqual(out["subtitle_chars"], 1500)

    def test_custom档里的非法值被夹住(self):
        cfg = {
            "ANALYSIS_DEPTH": "custom",
            "ANALYSIS_SUBTITLE_CHARS": -5,
            "ANALYSIS_RESULT_CHARS": 10**9,
            "MEDIA_MAX_FRAMES": "abc",
            "VIDEO_VISUAL_ANALYSIS_POLICY": "乱填",
        }
        out = resolve(cfg)
        self.assertGreater(out["subtitle_chars"], 0)
        self.assertLessEqual(out["result_chars"], 8000)
        self.assertGreaterEqual(out["max_frames"], 0)
        self.assertIn(out["visual_policy"], ("when_text_insufficient", "always", "never"))

    def test_配置读不了也不抛(self):
        class _Boom:
            def get(self, *a, **k):
                raise RuntimeError("炸了")

        out = resolve(_Boom())
        self.assertEqual(out["depth"], "standard")
        self.assertEqual(out["subtitle_chars"], 1500)


class HelperTests(unittest.TestCase):
    def test_便捷函数与resolve一致(self):
        cfg = {"ANALYSIS_DEPTH": "subtitle_only"}
        self.assertEqual(visual_policy(cfg), "never")
        self.assertEqual(subtitle_chars(cfg), DEPTH_PRESETS["subtitle_only"]["subtitle_chars"])
        self.assertEqual(result_chars(cfg), DEPTH_PRESETS["subtitle_only"]["result_chars"])

    def test_每段帧数便捷函数(self):
        self.assertEqual(frames_per_segment({"ANALYSIS_DEPTH": "unlimited"}), 12)
        self.assertEqual(frames_per_segment({"ANALYSIS_DEPTH": "standard"}), 5)
        self.assertEqual(frames_per_segment({"ANALYSIS_DEPTH": "subtitle_only"}), 0)


if __name__ == "__main__":
    unittest.main()
