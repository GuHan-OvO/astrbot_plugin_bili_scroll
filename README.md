# 我会一直刷B站 · astrbot_plugin_bili_scroll

让它有自己的 B站 日常：每天刷一遍，挑出值得看的，看完会在评论区**真的 @ 你**。

基于 [chenluQwQ/astrbot_plugin_bilibili_ai_bot](https://github.com/chenluQwQ/astrbot_plugin_bilibili_ai_bot) 的分支（`v1.8.0`）。
上游的评论回复、私信、直播弹幕、好感度、语义记忆、动态发布、联网查询全部保留。
完整上游文档见 [docs/upstream-readme.md](docs/upstream-readme.md)。

## 这个分支加了什么

| 能力 | 说明 | 相关配置 |
|---|---|---|
| **真 @ 提及** | 评论请求带 `at_name_to_mid`（`{"昵称": uid}` 的 JSON），B站 才会把正文里的 `@昵称` 解析成真实提及并通知对方；纯文本 @ 不会。读回 `content.members` 有值即为成功 | `OWNER_BILI_NAME`、`OWNER_MID` |
| **评论复核** | 带 @ 的评论发出 90 秒后读回一次，确认真的可见；被折叠或被吞都记进 `comment_verify_log.json` | 无 |
| **看过的视频** | 新页面 `pages/history`：封面卡片墙、按分数/心情/来源/是否推荐过筛选、分页、详情抽屉 | 无 |
| **详细程度档位** | 看多细由 `ANALYSIS_DEPTH` 决定：只看字幕 / 省 token / 标准 / 看更细 / 自定义 | `ANALYSIS_DEPTH` |
| **候选去重** | 同一 BV 只留播放量最高那份（总是生效）；标题高度相似的可选合并 | `DEDUPE_SIMILAR_TITLES` |
| **风控 412** | HTTP 412 不再当网络错误重试，直接清 WBI 缓存并返回可识别错误码 | 无 |
| **先落账后互动** | 评分一出就先写 `watch_log`，后续互动失败也不会丢「看过什么」 | 无 |
| **陪伴联动** | 可用 private_companion 7.0.0 的人格生成一句话，并走她的通道投递 | `PC_BRIDGE_ENABLE` |

## 快速开始

1. 把本仓库放进 AstrBot 的 `data/plugins/astrbot_plugin_bili_scroll`
2. 重载插件
3. 填下面几个必填配置
4. 在 QQ 里发 `bili主动` 跑一轮

### 必填配置

| 配置 | 说明 |
|---|---|
| `SESSDATA` / `BILI_JCT` | B站 登录态，用 `bili登录` 扫码获取。**扫码一次长期复用**，反复登录会累积风控 |
| `OWNER_BILI_NAME` | 你的 B站 昵称，用于 `@昵称` 的真实提及 |
| `OWNER_MID` | 你的 B站 UID，与昵称配对 |
| `ENABLE_PROACTIVE` | 主动看片总开关，**默认关** |

可选：`OWNER_QQ_UMO`（推荐私信投递地址，用 `biliUMO` 取）。

## 常用命令

| 命令 | 作用 |
|---|---|
| `bili主动` | 立即跑一轮主动看片 |
| `bili状态` | Cookie、计划、开关状态 |
| `bili登录` / `bili确认` | 扫码登录 |
| `bili开关` | 查看 / 切换各功能开关 |
| `biliUMO` | 取当前会话的 UMO，用于填 `OWNER_QQ_UMO` |
| `bili帮助` | 全部命令 |

其余命令（直播、番剧、记忆、好感度、黑名单、动态等）见 `docs/upstream-readme.md`。

## 看过的视频

入口：AstrBot WebUI → 插件 → **我会一直刷B站** → 页面「看过的视频」。

数据源是 `watch_log.json`，**只保留最近 200 条**（写入侧 `cap=200`）。想要更长的历史，需要改写入侧或另接 B站 的观看历史接口。

## 详细程度档位

| 档位 | 视觉分析 | 分段 | 帧 | 每日 token | 字幕上限 | 结果上限 |
|---|---|---|---|---|---|---|
| `subtitle_only` 只看字幕 | 不做 | 0 | 0 | 20k | 6000 | 3000 |
| `lean` 省 token | 按需 | 3 | 4 | 20k | 1500 | 1200 |
| `standard` 标准 | 按需 | 10 | 8 | 50k | 1500 | 1600 |
| `deep` 看更细 | 总是 | 20 | 16 | 150k | 6000 | 3000 |
| `custom` 自定义 | 读单项配置 | — | — | — | — | — |

`standard` 与改造前逐项一致，默认档不会改变任何现有行为。
非 `custom` 档时预设值覆盖单项配置；`custom` 时单选生效。

## 与陪伴联动（可选）

需要 `astrbot_plugin_private_companion` **7.0.0** 及以上，并给它打一个小补丁让「我会一直刷B站」出现在陪伴小屋：

```bash
cd <陪伴插件目录>
git apply --check <本仓库>/patches/private-companion-7.0.0-bili-scroll.patch
git apply <本仓库>/patches/private-companion-7.0.0-bili-scroll.patch
```

补丁说明与状态码含义见 [patches/README.md](patches/README.md)。插件侧开关是 `PC_BRIDGE_ENABLE`（默认关）。

## 与原版的关系

- **不跟踪上游更新**：`metadata.yaml` 的 `repo` 已清空，插件市场/检查更新不会覆盖本分支。
- 想吸收上游新功能时挑提交手动合，不要整目录替换。
- 上游历史保留在 git 祖先链里，`upstream` remote 仍指向上游仓库，方便对比与挑提交。

## 开发与测试

```bash
<astrbot venv>/Scripts/python.exe -m pytest tests -q
```

当前基线：`450 passed`，另有 1 个**上游既有失败**（`test_video_diagnostics.py::test_failed_download_records_underlying_reason`，与本次改动无关）。

本分支新增的模块：

| 模块 | 职责 |
|---|---|
| `core/mention.py` | 真 @ 映射的构造与校验 |
| `core/verify.py` | 评论发出后的读回复核 |
| `core/history.py` | 历史记录的过滤 / 分页 / 统计（纯函数） |
| `core/analysis_depth.py` | 详细程度档位解析 |
| `core/dedup.py` | 候选去重 |
| `core/pc_bridge.py` | 与 private_companion 的联动桥 |
| `core/extension_api.py` | 给陪伴看的 provider 状态门面 |
| `pages/history/` | 「看过的视频」页面 |

## 已知限制

- **历史只覆盖最近 200 条**（写入侧截断）。
- **复核只覆盖带 @ 的评论**：普通评论被折叠没那么关键，而 @ 那条是否可见决定功能成不成立。
- **复核的 `missing` 不等于被删**：热门视频里新评论很快会被顶出第一页，只记日志、不改账本。
- **未在真实 B站 账号上验证过 @ 的推送到达**：接口层的提及映射已实测成立（读回 `content.members`），但通知是否弹出取决于 B站 侧。

## 许可

原版 MIT，本分支沿用，保留原作者署名。
