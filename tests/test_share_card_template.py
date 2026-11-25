"""解析卡模板：默认精简、占位符渲染、空行剔除、自定义模板。

覆盖 2026-11-25 改动：原先卡片固定输出
「🎞️ B站视频解析 / ━━━ / 标题：… / UP主：…（UID:…） / 分区：未知分区 | 时长：… / 原链接：… / 简介：这个视频没有简介。 / 请稍等...视频一会发出」，
信息密度低且把「未知分区」「没有简介」这类空洞也发出来；模板也不可改。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.share import DEFAULT_SHARE_CARD_TEMPLATE, ShareMixin  # noqa: E402


class Probe(ShareMixin):
    def __init__(self, **config):
        self.config = dict(config)


INFO = {
    "bvid": "BV1AaBbCcDd",
    "title": "大小姐驾到《千问GO》！",
    "owner_name": "千问APP",
    "owner_mid": "3546929323575369",
    "tname": "",
    "duration": 189,
    "desc": "",
}


class ShareCardTemplateTests(unittest.TestCase):
    def card(self, **config):
        return Probe(**config)._build_share_card_text(dict(INFO), "")

    def test_默认模板只留四行关键信息(self):
        text = self.card(BILI_SHARE_PARSE_SEND_VIDEO=True)
        self.assertEqual(
            text.splitlines(),
            [
                "🎞️ 大小姐驾到《千问GO》！",
                "千问APP · 3:09",
                "https://www.bilibili.com/video/BV1AaBbCcDd",
                "视频稍后发出",
            ],
        )

    def test_不再出现空洞字段(self):
        text = self.card(BILI_SHARE_PARSE_SEND_VIDEO=True)
        for leaked in ("未知分区", "这个视频没有简介", "UID:", "━━━", "B站视频解析"):
            self.assertNotIn(leaked, text)

    def test_不发送视频时去掉提示行(self):
        text = self.card(BILI_SHARE_PARSE_SEND_VIDEO=False)
        self.assertEqual(len(text.splitlines()), 3)
        self.assertNotIn("视频稍后发出", text)

    def test_自定义模板生效(self):
        text = self.card(
            BILI_SHARE_PARSE_CARD_TEMPLATE="{title}\nUP：{up}\nUID：{uid}\n时长 {duration}"
        )
        self.assertEqual(
            text.splitlines(),
            ["大小姐驾到《千问GO》！", "UP：千问APP", "UID：3546929323575369", "时长 3:09"],
        )

    def test_空值行整行删掉(self):
        text = self.card(BILI_SHARE_PARSE_CARD_TEMPLATE="{title}\n{partition}\n{link}")
        self.assertEqual(len(text.splitlines()), 2)
        self.assertNotIn("未知分区", text)

    def test_未知占位符不原样发出(self):
        text = self.card(BILI_SHARE_PARSE_CARD_TEMPLATE="{title}\n{unknown_thing}")
        self.assertEqual(text.splitlines(), ["大小姐驾到《千问GO》！"])

    def test_模板留空回落到默认(self):
        text = self.card(BILI_SHARE_PARSE_CARD_TEMPLATE="   ", BILI_SHARE_PARSE_SEND_VIDEO=False)
        self.assertIn("🎞️ 大小姐驾到《千问GO》！", text)

    def test_默认模板常量包含视频提示占位符(self):
        self.assertIn("{video_hint}", DEFAULT_SHARE_CARD_TEMPLATE)
        self.assertIn("{link}", DEFAULT_SHARE_CARD_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
