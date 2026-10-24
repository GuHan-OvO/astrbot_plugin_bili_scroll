# 更新日志

本分支从 **v1.8.0** 起独立演进：`metadata.yaml` 的 `repo` 已清空，不跟随上游更新。
更早的版本历史属于上游项目，不在本仓库维护。

## v1.8.6 — 2026-10-25

### 自检页加「测私信」「测提及」

- **测私信**：给主人（`OWNER_MID`）发一条测试私信，验证 Cookie 与私信接口是否通。
- **测提及**：在**最近看过的一个视频**下发一条带真 @ 的评论。映射走
  `core/mention.py::build_mention_map(OWNER_BILI_NAME, OWNER_MID)`——只往正文拼 `@昵称`
  是纯文本，B站 不会推送，所以结果区会显示 `@映射` 是否为空。
- 路由 `POST trial/test`，body `{"kind": "private" | "mention"}`。
- 两个按钮共用 **30 秒冷却**（都是真实写操作）；未知 `kind` 直接报错，不猜。
- 结果区：私信显示收件人与内容；提及显示视频 / oid / @映射 / 评论正文。失败给具体原因
  （Cookie 失效 / 评论区关闭 / 敏感词 / 风控）。
## v1.8.5 — 2026-10-25

### 修「看过的视频」没有封面

- **根因**：写 `watch_log` 时取的是 `video.get("pic")`，而候选字典里根本没有 `pic` 键；
  真正带封面的是 `analysis_info`（合并了 view API 的结果）。实测三条记录 `pic` 全是空串，
  所以前端只能显示「无法获取封面」。
- 改为 `analysis_info.get("pic") or video.get("pic", "")`，共 5 处写入点
  （`_run_proactive_inner` 三处、`_run_special_follow_inner` 两处）。
  中途误改了一处**搜索候选构造**（那里没有 `analysis_info`，会 NameError），已回退。
- 前端封面 `img` 加 `referrerPolicy = "no-referrer"`，避开 B站 图床的防盗链判定。
- **老记录不会自动补封面**：那几条写入时就没存，只有之后新刷的才带。

### 冷却 300 秒 → 30 秒

300 秒实测太钝——一轮本身就要一两分钟，跑完再罚站五分钟才能继续。30 秒足够挡住连点。
## v1.8.4 — 2026-10-25

### 防连点

- 「刷一个」加冷却：两次真刷至少隔 **300 秒**（`LIVE_COOLDOWN_SECONDS`）。冷却期按钮禁用，
  剩余秒数显示在提示行（按钮文字仍保持 4 字以内）。
- 冷却状态存在后端（plugin 实例属性），**刷新页面也拦得住**——按钮 disabled 只能挡当前页面。
- `GET trial/live` 返回 `cooldown_remaining` / `cooldown_total`，页面初始化时据此恢复禁用状态；
  被拒时返回 `retry_after`，前端立刻进入倒计时而不是只弹一句原因。
- 每刷一次都是一组真实的 B站 写操作，风控是累积的，这是加冷却的理由。
## v1.8.3 — 2026-10-25

### 试运行改成真的刷一个视频

- 自检页的「试运行」按钮改为**「刷一个」**：不再干跑，而是走主流程
  `_run_proactive(max_watch=1)`——真的取片、分析、评价、**按配置互动**，并且真的写 `watch_log`。
- 一轮可能 1~3 分钟，所以改成后台任务 + 轮询：`POST trial/live` 立即返回启动结果，
  `GET trial/live` 返回 `running` / `elapsed_ms` / 这一轮看的视频与动作。
- 结果区显示：看了哪个视频、几分、什么心情、动了哪些手（点赞/投币/评论/@）、它说了什么。
- 重复点击会被拒（上一轮没跑完时返回 `started: false` 与原因），避免并发刷片。
- 保留原干跑接口 `POST trial`（只取片预览、不写任何东西），排查链路时仍可用。
## v1.8.2 — 2026-10-25

> 1.8.1 未单独发布，WebUI 整体重构与用量台账合并进本版。

### 用量与成本台账（后端）

- 新增 `core/usage.py`：把每次模型调用的 token 记进 `usage_log.jsonl`（按天裁剪 30 天），
  可按天 / 按用途 / 按模型聚合，并给出今日预算使用率。
- `core/llm.py` 三处埋点：AstrBot provider 走 `TokenUsage`（未缓存输入 / 缓存输入 / 输出三段，
  缓存输入单独记，因为它单价低一个量级）；独立 OpenAI 兼容 API 走 `CompletionUsage`
  （含 `prompt_tokens_details.cached_tokens`）。用途名随 `SUMMARY` / `GENERATION` 等分开记账。
- 新增只读路由 `GET usage/stats?days=1`：窗口汇总、今日、按用途、按模型、每日明细、预算使用率。
- 记账永不抛异常：盘满、只读、半行 JSON 都只跳过，绝不影响业务。

### WebUI 整体重构（前端）

样式层重建为 `pages/bilibot/design/`（tokens / base / shell / components / pages / studio / motion
＋ 第二轮 motion-pro），外壳改为悬浮玻璃侧边栏 + 粘性顶栏 + 内容列；深浅色、页面分层转场、
指针光照、滚动叙事、浮层景深。旧 `styles.css` / `creator.css` / `theme.css` 删除。

### 已知限制

- 媒体理解模块（`core/media/understanding.py`）**尚未接入主流程**（全仓无实例化点），
  所以没有它的「缓存命中率」可讲；用量台账只覆盖真正在跑的模型调用。
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
