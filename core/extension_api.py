"""对外只读门面：让 private_companion 7.0.0 的 provider 机制能发现本插件。

7.0.0 的 `astrbot_host/integration_registry.py::_provider()` 做的是：

    api = star.star_cls.extension_api          # 插件实例属性
    status = api.companion_v2_status()          # 必须是同步函数（async 会被拒）
    # 然后校验：schema == "companion.provider-status.v1"、plugin_id 匹配、
    # enabled 是 bool、runtime_ready 是 bool 或 None

所以这里只暴露「状态」，不暴露任何可执行能力 —— 对方拿到后只用于显示，
不会调用本插件做任何事。
"""

STATUS_SCHEMA = "companion.provider-status.v1"
"""与 PC 侧 STATUS_SCHEMA 常量一致，写错会被判无效契约。"""

PLUGIN_ID = "astrbot_plugin_bilibili_ai_bot"
"""必须与 PC 的 integration_catalog.EXTERNAL_PROVIDERS 里登记的 plugin_id 完全一致。"""


class BiliBotExtensionApi:
    """给其它插件看的门面对象。刻意只读。"""

    api_version = "bilibili.bot.v1"

    def __init__(self, plugin):
        self._plugin = plugin

    def companion_v2_status(self) -> dict:
        """同步返回接入状态。

        PC 侧明确拒绝 async（`raise ValueError("asynchronous status is not supported")`），
        所以这里不能是 coroutine。
        """
        return {
            "schema": STATUS_SCHEMA,
            "plugin_id": PLUGIN_ID,
            "enabled": self._enabled(),
            "runtime_ready": self._runtime_ready(),
        }

    def _enabled(self) -> bool:
        """「主动看片」总开关是否打开。读不到配置就当关闭，不抛异常。"""
        try:
            return bool(self._plugin.config.get("ENABLE_PROACTIVE", False))
        except Exception:
            return False

    def _runtime_ready(self):
        """已配置登录 → True；没配置 → False；读取异常 → None（PC 允许 None）。"""
        try:
            sessdata = str(self._plugin.config.get("SESSDATA", "") or "").strip()
        except Exception:
            return None
        return bool(sessdata)
