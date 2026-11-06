"""日志安全包装：把日志流编码放不下的字符替换掉。

AstrBot 的 loguru sink 用系统控制台编码（本机是 GBK）写盘。行里带 emoji 时
``stream.write`` 抛 UnicodeEncodeError，loguru 会把**整行丢掉** —— 日志里看起来
「什么都没发生」，实际动作已经执行（例如「📢 已在评论区@主人」这条真实发生过，
日志里 0 命中，排查时极易误判）。

这里在写日志之前做一次可编码性检查，替换掉不可编码的字符，保住整行。
"""
import sys

from astrbot.api import logger as _logger

_ENCODING = None


def _stream_encoding():
    for stream in (sys.stderr, sys.stdout):
        encoding = getattr(stream, "encoding", None)
        if encoding:
            return encoding
    return "utf-8"


def safe_text(value):
    """把无法编码到日志流的字符换成 '?'，其余原样返回。"""
    global _ENCODING
    if not isinstance(value, str):
        return value
    if _ENCODING is None:
        _ENCODING = _stream_encoding()
    try:
        value.encode(_ENCODING)
        return value
    except (UnicodeEncodeError, LookupError):
        pass
    try:
        return value.encode(_ENCODING, "replace").decode(_ENCODING, "replace")
    except (LookupError, UnicodeDecodeError):
        return value.encode("ascii", "replace").decode("ascii")


class _SafeLogger:
    """只转发 loguru 的基础方法，写入前清洗消息文本。"""

    _LEVELS = (
        "trace", "debug", "info", "success", "warning", "error", "critical", "exception",
    )

    def __getattr__(self, name):
        target = getattr(_logger, name)
        if name not in self._LEVELS:
            return target

        def _wrapped(message=None, *args, **kwargs):
            return target(safe_text(message), *args, **kwargs)

        return _wrapped


logger = _SafeLogger()
