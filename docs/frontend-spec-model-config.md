# 前端规格 · 模型配置与配置分区

> 面向 v1.9.0。本文描述前端需要实现的内容；后端能力已在同版本落地，接口契约以本文为准。
> 后端改动见 `CHANGELOG.md` 的 v1.9.0 段。

## 一、本轮已实现 / 待前端实现

| 项 | 状态 |
|---|---|
| 模型清单接口 `GET model-options` | 已实现 |
| 配置分组接口 `GET config/groups` | 已实现 |
| 侧边栏「模型配置」入口 + 模型页 | 已实现（`pages/bilibot/app.js`） |
| 8 个模型项渲染为下拉 | 已实现 |
| **基础设置 / 全部配置 两个 tab 按 8 类细分** | **待前端实现**（后端 `config/groups` 已就绪） |
| `pages/config` 独立页复用同一份分组 | **待前端实现** |
| 移除 `app.js` 中两份硬编码分组表 | **待前端实现** |

## 二、侧边栏入口（关键约束）

宿主 WebUI 的「插件页面」分组生成逻辑如下：

```js
// 依据 dashboard 构建产物，非源码
const d = plugins.filter((p) => p.activated && Array.isArray(p.pages) && p.pages.length > 0);
const items = d.map((p) => ({ title: p.display_name || p.name, to: `/plugin-page/${p.name}/${p.pages[0]}` }));
```

**每个插件仅取 `pages[0]`**，而 `discover_plugin_pages()` 按目录名字母序返回
（`astrbot/dashboard/services/plugin_page_service.py`），故 `bilibot` < `config`。

结论：
- 新建 `pages/model/` **不会**出现在宿主侧边栏；
- 通过改目录名抢占首位，会使控制中心入口被挤掉。

因此模型页实现为 **SPA 内页面**，入口位于插件自身的侧边栏：

```
NAV_GROUPS = [["配置", ["models", "basics", "allconfig"]]]
NAV_ITEMS += ["models", "lightning", "模型配置", "各项功能所使用的模型"]
```

## 三、模型页规格

### 3.1 结构

```
页头（MODELS / 模型配置 / 说明 / 「重新读取」按钮）
├── 模型来源卡：各能力可用模型数 + 当前默认对话模型
├── 对话模型：7 个下拉
├── 向量模型：EMBED_PROVIDER_ID 下拉
└── 独立 Embedding 接口（折叠）：EMBED_API_KEY / EMBED_API_BASE / EMBED_MODEL / EMBED_TIMEOUT_SECONDS
```

### 3.2 下拉项

| 属性 | 规则 |
|---|---|
| 候选范围 | 仅 AstrBot 中**已启用**的模型；未启用的 provider 不进入候选 |
| 首项 | 对话类：「（用 AstrBot 默认）」，值为 `""`；向量类：「（用下面的独立接口）」，值为 `""` |
| 选项文本 | `<模型名> · <维度> · <状态>`，状态仅在值为「未加载」时显示 |
| 当前值已不存在 | 追加 `<option value="原值" selected>⚠ 原值（已不存在）</option>`，不得静默回落至首项 |
| 候选为空 | 仍渲染下拉（仅含首项），不设置 `disabled`，以免无法清除已保存的旧值 |
| 保存 | 沿用既有 `data-config-key` + `setDraft` + 底部保存 dock，不新增保存通道 |

### 3.3 能力分区

| capability | 中文名 | 是否可配置 |
|---|---|---|
| `chat` | 对话模型 | 是（7 个键） |
| `embedding` | 向量模型 | 是（`EMBED_PROVIDER_ID`） |
| `rerank` / `tts` / `stt` | 重排序 / 语音合成 / 语音识别 | 否，仅在「模型来源」卡中显示数量 |

## 四、接口契约

### `GET model-options`

```json
{
  "groups": [
    {"capability": "chat", "label": "对话模型", "items": [
      {"id": "星渊（gemini/gemini-3.1-flash-lite", "model": "gemini-3.1-flash-lite",
       "provider_type": "openai_chat_completion", "enabled": true, "loaded": true}
    ]},
    {"capability": "embedding", "label": "向量模型", "items": [
      {"id": "嵌入", "model": "bge-m3", "provider_type": "openai_embedding",
       "enabled": true, "loaded": true, "dim": 1024}
    ]},
    {"capability": "rerank", "label": "重排序模型", "items": []},
    {"capability": "tts", "label": "语音合成", "items": []},
    {"capability": "stt", "label": "语音识别", "items": []}
  ],
  "config_keys": {"LLM_PROVIDER_ID": "chat", "EMBED_PROVIDER_ID": "embedding"},
  "default_chat": "<当前默认对话模型 id 或空串>"
}
```

**硬约束**：`items` 每条仅允许 `id / model / provider_type / enabled / loaded / dim`。
响应中不得出现 `key`、`api_base`、`provider_config`、`custom_headers`、`proxy`
——宿主 `provider_config` 中这些字段为明文密钥，已由单元测试校验。

`enabled` 恒为 `true`（清单只含已启用模型），保留该字段用于稳定前端契约。

### `GET config/groups`

```json
{
  "groups": [
    {"id": "base", "label": "基础与账号", "hint": "...", "keys": ["SESSDATA", "..."], "prefixes": ["账号"]}
  ],
  "of_key": {"SESSDATA": "base", "LLM_PROVIDER_ID": "model"}
}
```

`groups` 的顺序即建议的 tab 顺序；空分组不出现；`of_key` 覆盖全部下发键
（不含 `SESSDATA` / `BILI_JCT` / `DEDE_USER_ID` / `REFRESH_TOKEN` 四个保护键）。

## 五、8 类分组与现有 tab 的对应

| id | label | 收纳的 `【】` 前缀 | 现有 18 组口径中的对应 |
|---|---|---|---|
| `base` | 基础与账号 | 账号、网络代理、兼容 | 账号与连接、兼容与系统 |
| `model` | 模型与能力 | 高级、总结模型、生成模型、模型可靠性、联网搜索 + 8 个模型键 | 人设与模型、联网搜索、高级能力 |
| `reply` | 回复与互动 | 回复、好感度、心情、评论复核、给主人推荐 | 回复与互动、好感度与心情 |
| `proactive` | 主动与日常 | 主动行为、主动看片、关注动态巡视、番剧、直播、动态、日/周总结、自主安排、行为调度、固定计划、作息、演化、观影日志、视频 | 番剧与动态、视频与看片、推荐与主动行为、总结、自主安排与作息、行为调度、性格演化 |
| `dm` | 私信与分享 | 私信、分享解析、跨端活动与分享、联动 | 私信、分享解析 |
| `persona` | 人格与记忆 | 人设、记忆隔离 | 与人设与模型、安全与记忆隔离交叉 |
| `security` | 安全 | 安全与工具、拉黑、恶意告警、特别关注 | 安全与记忆隔离 |
| `other` | 其它 | 未匹配任何前缀 | 兼容与系统（兜底） |

**与旧口径的两处差异**：
1. 模型键自「人设与模型」拆出独立成组，旧口径将 `LLM_PROVIDER_ID` 与人格配置混列；
2. 记忆隔离自「安全与记忆隔离」拆至「人格与记忆」，安全组仅保留风控相关项。

## 六、待做：两个 tab 的细分

当前 `pages/bilibot/app.js` 中存在三套口径：

| 位置 | 组数 | 处理方式 |
|---|---|---|
| `BASIC_GROUP_ORDER`（约 2240 行） | 11 | 移除，改用 `config/groups` |
| `ALL_CONFIG_GROUPS` / `ALL_CONFIG_TAG_GROUP`（约 2321 行） | 18 | 移除，改用 `config/groups` |
| `pages/config/config.js` 的 `groupName()` | 45 | 移除，改用 `config/groups` |

改造要求：
1. 初始化时请求一次 `GET config/groups`，缓存 `of_key` 与 `groups`；
2. 「基础设置」tab 改为 8 个功能域分区（当前仅显示两组，实际按 `basicGroupFor` 过滤）；
3. 「全部配置」tab 改为 8 个分区 + 「全部」视图，移除 18 组硬编码；
4. `pages/config` 独立页同样仅依据 `of_key` 分组，不再解析 `【】`；
5. **禁止**在三个前端中各写一份前缀表，分组真源只能有一份。

## 七、验收清单

1. 侧边栏「配置」组下存在「模型配置」，点击后进入模型页
2. 8 个模型项在模型页渲染为下拉，选项来自 `model-options`
3. 在 AstrBot 中禁用的模型不出现在下拉中
4. 某 provider 被删除后，页面显示「⚠ 原值（已不存在）」而非静默回落至默认项
5. `model-options` 响应原文中检索不到 `key` / `api_base`（可通过浏览器 Network 面板核对）
6. `config/groups` 的 `of_key` 覆盖 `config/schema` 全部键
7. 同一配置键在「基础设置」与「全部配置」中归属同一分区
8. 模型页修改后切换页面再返回，未保存的值仍然保留（走 `dirtyKeys`）
9. 向量模型下拉与「独立 Embedding 接口」的互斥关系有明确文案说明
10. 页面在浅色 / 深色 / 工作室三套令牌下均无样式错位
