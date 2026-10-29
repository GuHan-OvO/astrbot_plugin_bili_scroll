"""模型清单导出的离线测试。

重点守三件事：禁用项不能漏、密钥不能漏、单个 provider 出错不能拖垮整张清单。
"""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_autonomous_ranges import _install_astrbot_stub  # noqa: E402

_install_astrbot_stub()

from core.model_options import collect_model_options  # noqa: E402


class _PType:
    def __init__(self, value):
        self.value = value


class _Meta:
    def __init__(self, pid, model, adapter, provider_type):
        self.id = pid
        self.model = model
        self.type = adapter
        self.provider_type = _PType(provider_type)


class _Provider:
    def __init__(self, pid, model, adapter="openai_chat_completion", provider_type="chat_completion"):
        self._meta = _Meta(pid, model, adapter, provider_type)

    def meta(self):
        return self._meta


class _BrokenProvider:
    def meta(self):
        raise RuntimeError("meta 坏了")


class _EmbeddingProvider(_Provider):
    def __init__(self, pid, model, dim=1024):
        super().__init__(pid, model, "openai_embedding", "embedding")
        self._dim = dim

    def get_dim(self):
        return self._dim


class _Ctx:
    def __init__(
        self,
        *,
        chat_insts=None,
        embed_insts=None,
        rerank_insts=None,
        providers_config=None,
        provider_sources_config=None,
        default=None,
    ):
        self.provider_manager = types.SimpleNamespace(
            provider_insts=list(chat_insts or []),
            embedding_provider_insts=list(embed_insts or []),
            rerank_provider_insts=list(rerank_insts or []),
            providers_config=list(providers_config or []),
            provider_sources_config=list(provider_sources_config or []),
        )
        self._default = default

    def get_all_providers(self):
        return self.provider_manager.provider_insts

    def get_all_embedding_providers(self):
        return self.provider_manager.embedding_provider_insts

    def get_using_provider(self):
        return self._default


def _items(payload, capability):
    for group in payload["groups"]:
        if group["capability"] == capability:
            return group["items"]
    raise AssertionError(f"没有 {capability} 分组")


def _walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


class CollectModelOptionsTests(unittest.TestCase):
    def test_未启用的模型不进入候选(self):
        # 未启用的 provider 不会被 AstrBot 加载，选中后也无法调用，故不纳入候选
        ctx = _Ctx(
            chat_insts=[_Provider("启用中的模型", "glm-5")],
            providers_config=[
                {"id": "启用中的模型", "enable": True, "model": "glm-5", "provider_source_id": "s1"},
                {"id": "停用的模型", "enable": False, "model": "qwen", "provider_source_id": "s1"},
            ],
            provider_sources_config=[{"id": "s1", "provider_type": "chat_completion"}],
        )
        payload = collect_model_options(ctx)
        ids = [item["id"] for item in _items(payload, "chat")]
        self.assertIn("启用中的模型", ids)
        self.assertNotIn("停用的模型", ids)

    def test_已启用但尚未加载的模型仍进入候选(self):
        # 实例列表只含已加载项；配置里已启用但未加载的需由 providers_config 补齐
        ctx = _Ctx(
            providers_config=[
                {"id": "已启用未加载", "enable": True, "model": "m", "provider_source_id": "s1"},
            ],
            provider_sources_config=[{"id": "s1", "provider_type": "chat_completion"}],
        )
        items = _items(collect_model_options(ctx), "chat")
        self.assertEqual([item["id"] for item in items], ["已启用未加载"])
        self.assertFalse(items[0]["loaded"])

    def test_chat条目按provider_source回填类型(self):
        # 真实配置里 chat 条目的 provider_type 是空串，类型记在 source 上
        ctx = _Ctx(
            providers_config=[{"id": "别名模型", "enable": True, "model": "m", "provider_source_id": "src-a"}],
            provider_sources_config=[{"id": "src-a", "provider_type": "chat_completion"}],
        )
        payload = collect_model_options(ctx)
        self.assertEqual([item["id"] for item in _items(payload, "chat")], ["别名模型"])

    def test_运行时条目与配置条目合并(self):
        ctx = _Ctx(
            chat_insts=[_Provider("同一个", "实例模型名")],
            providers_config=[{"id": "同一个", "enable": True, "model": "配置模型名", "provider_source_id": "s"}],
            provider_sources_config=[{"id": "s", "provider_type": "chat_completion"}],
        )
        items = _items(collect_model_options(ctx), "chat")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["loaded"])
        # 运行中的模型名是实际在用的那个，优先于配置里写的
        self.assertEqual(items[0]["model"], "实例模型名")

    def test_向量模型带维度且单独分组(self):
        ctx = _Ctx(embed_insts=[_EmbeddingProvider("嵌入", "bge-m3", 1024)])
        payload = collect_model_options(ctx)
        embedding = _items(payload, "embedding")
        self.assertEqual(embedding[0]["id"], "嵌入")
        self.assertEqual(embedding[0]["dim"], 1024)
        self.assertEqual(_items(payload, "chat"), [])

    def test_返回体不得包含任何密钥字段(self):
        ctx = _Ctx(
            chat_insts=[_Provider("模型A", "m")],
            providers_config=[
                {
                    "id": "模型A",
                    "enable": True,
                    "model": "m",
                    "provider_source_id": "s",
                    # 下面这些在真实配置里就是明文，绝不能被带出去
                    "key": ["sk-secret"],
                    "api_base": "https://example.invalid",
                    "embedding_api_key": ["sk-embed"],
                    "rerank_api_key": ["sk-rerank"],
                }
            ],
            provider_sources_config=[{"id": "s", "provider_type": "chat_completion"}],
        )
        payload = collect_model_options(ctx)
        flat = set(_walk_keys(payload))
        for forbidden in ("key", "api_base", "embedding_api_key", "rerank_api_key", "provider_config", "custom_headers", "proxy"):
            self.assertNotIn(forbidden, flat)
        self.assertNotIn("sk-secret", str(payload))

    def test_单个provider元信息异常不影响其它项(self):
        ctx = _Ctx(chat_insts=[_BrokenProvider(), _Provider("正常模型", "m")])
        items = _items(collect_model_options(ctx), "chat")
        self.assertEqual([item["id"] for item in items], ["正常模型"])

    def test_默认对话模型与配置键映射(self):
        ctx = _Ctx(default=_Provider("默认模型", "m"))
        payload = collect_model_options(ctx)
        self.assertEqual(payload["default_chat"], "默认模型")
        self.assertEqual(payload["config_keys"]["LLM_PROVIDER_ID"], "chat")
        self.assertEqual(payload["config_keys"]["EMBED_PROVIDER_ID"], "embedding")

    def test_没有provider管理器也不崩(self):
        payload = collect_model_options(object())
        self.assertEqual([group["items"] for group in payload["groups"]], [[], [], [], [], []])


if __name__ == "__main__":
    unittest.main()
