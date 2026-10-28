"""「看视频有多细」的三档预设。

chenlu 原版把这些旋钮散在四处（视觉策略、分段数、帧数、token 预算、两处字数截断），
其中三处还是写死的，用户在 WebUI 里根本调不到。这里收成一份预设表：

- ``subtitle_only`` 只看字幕（完全不看画面）
- ``lean``          省 token
- ``standard``      **等于原版行为**（升级后什么都不变）
- ``deep``          看更细
- ``custom``        用下面各单项的值，等价于老用户逐项调

冲突规则（写进 hint，代码照此实现）：只要不是 ``custom``，预设值**覆盖**单项配置；
``custom`` 时单项配置生效。

``standard`` 的每一项都逐字等于原版默认值，所以默认档不会改变任何现有行为。
"""

from __future__ import annotations

DEFAULT_DEPTH = "standard"
CUSTOM_DEPTH = "custom"

# 预设表。键名与配置项对应，方便对照。
DEPTH_PRESETS: dict[str, dict] = {
    "subtitle_only": {
        "visual_policy": "never",
        "segment_max_count": 0,
        "max_frames": 0,
        "frames_per_segment": 0,
        "token_budget_daily": 20000,
        "subtitle_chars": 6000,
        "result_chars": 3000,
    },
    "lean": {
        "visual_policy": "when_text_insufficient",
        "segment_max_count": 3,
        "max_frames": 4,
        "frames_per_segment": 4,
        "token_budget_daily": 20000,
        "subtitle_chars": 1500,
        "result_chars": 1200,
    },
    # standard 必须与原版硬编码值逐项一致：1500 / 1600 / 10 / 8 / 50000
    "standard": {
        "visual_policy": "when_text_insufficient",
        "segment_max_count": 10,
        "max_frames": 8,
        "frames_per_segment": 5,
        "token_budget_daily": 50000,
        "subtitle_chars": 1500,
        "result_chars": 1600,
    },
    "deep": {
        "visual_policy": "always",
        "segment_max_count": 20,
        "max_frames": 16,
        "frames_per_segment": 8,
        "token_budget_daily": 150000,
        "subtitle_chars": 6000,
        "result_chars": 3000,
    },
    # 无限制：不看预算、不砍段数、字幕与结果都不截断。
    # 段数 360 覆盖 30 小时（B站单视频远达不到），等价于"全片都分析"；
    # 帧数受单次请求的图片数量限制，固定 12 帧/段（=每 25 秒一帧，300 秒一段时）。
    "unlimited": {
        "visual_policy": "always",
        "segment_max_count": 360,
        "max_frames": 64,
        "frames_per_segment": 12,
        "token_budget_daily": 2000000,
        "subtitle_chars": 20000,
        "result_chars": 8000,
    },
}

# custom 档（以及没配置时）读这些键
_CUSTOM_KEYS = {
    "visual_policy": ("VIDEO_VISUAL_ANALYSIS_POLICY", "when_text_insufficient", str),
    "segment_max_count": ("VIDEO_SEGMENT_MAX_COUNT", 10, int),
    "max_frames": ("MEDIA_MAX_FRAMES", 8, int),
    "token_budget_daily": ("MEDIA_TOKEN_BUDGET_DAILY", 50000, int),
    "subtitle_chars": ("ANALYSIS_SUBTITLE_CHARS", 1500, int),
    "result_chars": ("ANALYSIS_RESULT_CHARS", 1600, int),
}

VALID_VISUAL_POLICIES = ("when_text_insufficient", "always", "never")


def _clamp_int(value, *, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _read_custom(config) -> dict:
    out: dict = {}
    for name, (key, default, caster) in _CUSTOM_KEYS.items():
        raw = config.get(key, default)
        if caster is str:
            text = str(raw or default).strip()
            out[name] = text if text in VALID_VISUAL_POLICIES else default
        elif name == "segment_max_count":
            out[name] = _clamp_int(raw, low=0, high=50, fallback=int(default))
        elif name == "max_frames":
            out[name] = _clamp_int(raw, low=0, high=64, fallback=int(default))
        elif name == "token_budget_daily":
            out[name] = _clamp_int(raw, low=1000, high=2_000_000, fallback=int(default))
        elif name == "subtitle_chars":
            out[name] = _clamp_int(raw, low=200, high=20000, fallback=int(default))
        else:  # result_chars
            out[name] = _clamp_int(raw, low=200, high=8000, fallback=int(default))
    # 自定义档没有独立键：每段帧数沿用 MEDIA_MAX_FRAMES（0 = 不抽帧）
    out["frames_per_segment"] = out["max_frames"]
    return out


def resolve(config) -> dict:
    """算出这一轮真正生效的一组参数。任何异常都退回 standard，不抛给调用方。"""
    try:
        depth = str(config.get("ANALYSIS_DEPTH", DEFAULT_DEPTH) or DEFAULT_DEPTH).strip()
    except Exception:
        depth = DEFAULT_DEPTH

    preset = DEPTH_PRESETS.get(depth)
    if depth != CUSTOM_DEPTH and preset is not None:
        return {"depth": depth, **preset}

    effective_depth = CUSTOM_DEPTH if depth == CUSTOM_DEPTH else DEFAULT_DEPTH
    try:
        custom = _read_custom(config)
    except Exception:
        custom = dict(DEPTH_PRESETS[DEFAULT_DEPTH])
    return {"depth": effective_depth, **custom}


def visual_policy(config) -> str:
    return resolve(config)["visual_policy"]


def frames_per_segment(config) -> int:
    """每段送多少帧给视觉模型（已由 resolve 保证是 0~64 的整数）。"""
    return int(resolve(config)["frames_per_segment"])


def subtitle_chars(config) -> int:
    return resolve(config)["subtitle_chars"]


def result_chars(config) -> int:
    return resolve(config)["result_chars"]
