# 更新日志

本分支从 **v1.8.0** 起独立演进：`metadata.yaml` 的 `repo` 已清空，不跟随上游更新。
更早的版本历史属于上游项目，不在本仓库维护。

## v1.8.0 — 2026-10-24

### 新增

- **真 @ 提及**：发评论时带上 `at_name_to_mid` 映射，B站 才会把正文里的 `@昵称` 解析成
  真实提及并通知对方；读回 `content.members` 有值即为成功。纯文本 @ 不会通知。
- **评论复核**：带 @ 的评论发出 90 秒后读回一次，确认真的可见；被折叠或被吞都记进
  `comment_verify_log.json`。`missing` 只表示「没在前 20 条里」，不等于被删。
- **看过的视频页面**（`pages/history`）：封面卡片墙、按分数 / 心情 / 来源 / 是否推荐过 /
  是否评价失败 / 关键词筛选、分页、详情抽屉。
- **详细程度档位** `ANALYSIS_DEPTH`：`subtitle_only` / `lean` / `standard` / `deep` / `custom`。
  `standard` 与旧版行为逐项一致；非 `custom` 档时预设覆盖单项配置。
- **候选去重**：同一 BV 只留播放量最高那份（总是生效）；标题高度相似的可选合并
  （`DEDUPE_SIMILAR_TITLES`，默认关）。
- **陪伴联动**（可选）：`PC_BRIDGE_ENABLE` 开启后，QQ 推荐可借用
  `astrbot_plugin_private_companion` 7.0.0 的人格生成与通道投递，失败自动回退到本插件直发。
- **对外 provider 门面**：`extension_api.companion_v2_status()`，供陪伴插件在
  `/integration/manifest` 中识别本插件。

### 行为变更

- **HTTP 412 不再重试**：B站 风控页返回 HTML 而不是 JSON，原来会被当成网络错误重试三次；
  现在直接清 WBI 缓存并返回 `{"code": -412}`，避免加重限流。
- **先落账后互动**：评分一出就先写 `watch_log`，后续互动失败也不会丢「看过什么」。
- **包名**：`astrbot_plugin_bilibili_ai_bot` → `astrbot_plugin_bili_scroll`（目录、模块名、
  `PLUGIN_ID`、WebUI 路由、数据目录全部随之变更；从旧版迁移需重命名 `plugin_data` 目录）。
- **显示名**：`我会自己刷B站`；版本号 `1.7.2` → `1.8.0`；`repo` 清空，不再接受市场更新覆盖。

### 新增配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `ANALYSIS_DEPTH` | `standard` | 看多细：只看字幕 / 省 token / 标准 / 看更细 / 自定义 |
| `ANALYSIS_SUBTITLE_CHARS` | `1500` | 送进提示词的字幕上限（仅 `custom` 档生效） |
| `ANALYSIS_RESULT_CHARS` | `1600` | 分析结果进上下文的截断长度（仅 `custom` 档生效） |
| `MEDIA_MAX_FRAMES` | `8` | 视觉分析抽帧上限（仅 `custom` 档生效） |
| `MEDIA_TOKEN_BUDGET_DAILY` | `50000` | 每日媒体理解 token 上限（仅 `custom` 档生效） |
| `DEDUPE_SIMILAR_TITLES` | `false` | 是否合并标题高度相似的候选 |
| `PC_BRIDGE_ENABLE` | `false` | 是否借用陪伴插件的人格与通道 |

`VIDEO_VISUAL_ANALYSIS_POLICY` 增加第三个取值 `never`（完全不做视觉分析）。

### 开发

- 新增模块：`mention` / `verify` / `history` / `analysis_depth` / `dedup` / `pc_bridge` / `extension_api`。
- 测试：`pytest tests -q` → `450 passed`，另有 1 个上游既有失败
  （`test_video_diagnostics.py::test_failed_download_records_underlying_reason`）。
