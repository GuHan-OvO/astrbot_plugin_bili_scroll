import json
import unittest

from core.video_evaluation import VideoEvaluationError, parse_video_evaluation


def payload(**overrides):
    value = {
        "score": 8.6,
        "score_reason": "喜欢人物之间克制但持续变化的关系",
        "comment": "最后那个停顿比台词还狠",
        "mood": "感动",
        "review": "没有硬煽情，反倒被最后一个小动作击中了。",
        "want_follow": True,
        "recommend_owner": False,
        "recommend_reason": "",
        "partition": "动画",
        "preference_signals": [
            {
                "type": "work", "value": "守塔人", "polarity": "like",
                "strength": 0.85, "evidence": "喜欢人物关系和克制叙事",
            },
            {
                "type": "character", "value": "守塔人父子", "polarity": "curious",
                "strength": 0.7, "evidence": "想继续了解人物关系",
            },
        ],
        "search_keywords": ["守塔人 人物解析", "克制叙事 动画"],
    }
    value.update(overrides)
    return value


class VideoEvaluationSchemaTests(unittest.TestCase):
    def parse(self, value):
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return parse_video_evaluation(raw)

    def test_preserves_decimal_score_and_concrete_signals(self):
        result = self.parse(payload())
        self.assertEqual(result["score"], 8.6)
        self.assertEqual(result["preference_signals"][0]["value"], "守塔人")
        self.assertEqual(result["search_keywords"][0], "守塔人 人物解析")

    def test_plain_text_partial_json_and_extra_fields_are_rejected(self):
        for value in ("挺好看的，8分", '{"score":8', payload(analysis="内部分析")):
            with self.subTest(value=value):
                with self.assertRaises(VideoEvaluationError):
                    self.parse(value)

    def test_signal_count_and_types_are_bounded(self):
        too_many = payload(
            preference_signals=[payload()["preference_signals"][0]] * 6
        )
        with self.assertRaises(VideoEvaluationError):
            self.parse(too_many)
        bad = payload()
        bad["preference_signals"][0]["type"] = "everything"
        with self.assertRaises(VideoEvaluationError):
            self.parse(bad)

    def test_owner_recommendation_requires_concrete_reason(self):
        with self.assertRaises(VideoEvaluationError):
            self.parse(payload(recommend_owner=True, recommend_reason=""))

    def test_self_enjoyment_is_enough_to_express_a_share_intent(self):
        result = self.parse(payload(
            score=9,
            recommend_owner=True, recommend_reason="实拍机关的做法让我很想分享",
        ))
        self.assertEqual(result["score"], 9)
        self.assertTrue(result["recommend_owner"])
        self.assertEqual(result["recommend_reason"], "实拍机关的做法让我很想分享")

    def test_overlong_free_text_is_clipped_instead_of_rejected(self):
        """2026-11-24 实测：score_reason 超 120 字让整条评价作废，代价太大。"""
        result = self.parse(payload(
            score_reason="很" * 200,
            comment="好" * 120,
            review="看" * 260,
            partition="分" * 60,
            search_keywords=["词" * 60],
        ))
        self.assertEqual(result["score"], 8.6)
        self.assertEqual(len(result["score_reason"]), 120)
        self.assertEqual(len(result["comment"]), 80)
        self.assertEqual(len(result["review"]), 180)
        self.assertEqual(len(result["partition"]), 30)
        self.assertEqual(len(result["search_keywords"][0]), 40)

    def test_overlong_signal_fields_are_clipped(self):
        signals = [{
            "type": "work", "value": "作" * 80, "polarity": "like",
            "strength": 0.8, "evidence": "证" * 160,
        }]
        result = self.parse(payload(preference_signals=signals))
        self.assertEqual(len(result["preference_signals"][0]["value"]), 50)
        self.assertEqual(len(result["preference_signals"][0]["evidence"]), 100)

    def test_enum_and_type_errors_still_reject(self):
        """截断只对「只是啰嗦」生效；类型错与枚举错仍然判失败。"""
        for bad in (
            payload(mood="随便"),
            payload(score_reason=123),
            payload(score="8.6"),
        ):
            with self.subTest(bad=bad), self.assertRaises(VideoEvaluationError):
                self.parse(bad)

    def test_personal_score_rejects_non_numeric_and_non_finite_values(self):
        for score in (True, "9", -1, 11, float("nan"), float("inf")):
            with self.subTest(score=score), self.assertRaises(VideoEvaluationError):
                self.parse(payload(score=score))


if __name__ == "__main__":
    unittest.main()
