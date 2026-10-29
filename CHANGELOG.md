# 更新日志

本分支从 **v1.8.0** 起独立演进：`metadata.yaml` 的 `repo` 已清空，不跟随上游更新。
更早的版本历史属于上游项目，不在本仓库维护。

## v1.9.0 — 2026-10-30

### 模型选择改为读取 AstrBot 已启用的模型

- 新增 `GET model-options`：将 AstrBot 中已启用的对话 / 向量 / 重排序 / 语音合成 /
  语音识别模型整理为清单下发。7 个 `*_PROVIDER_ID` 与新增的 `EMBED_PROVIDER_ID`
  由手工填写改为下拉选择。
- **仅导出已启用的模型**：未启用的 provider 不会被 AstrBot 加载，选中后无法调用，
  因此不进入候选。`context.get_all_*()` 只返回已启用的提供商，故清单同时读取
  `provider_manager.providers_config`，以补齐「已启用但尚未加载」的条目。
- **密钥不外泄**：`provider_config` 中的 `key` / `embedding_api_key` / `rerank_api_key`
  为明文，本接口每条仅输出 `id / model / provider_type / enabled / loaded`
  （向量模型额外输出 `dim`），并由测试以递归扫描校验该约束。
- chat 条目自身不含 `provider_type`（类型记录在 `provider_sources` 中），需按
  `provider_source_id` 回填，否则按能力过滤将得到空列表。

### 新增「模型配置」页

- 侧边栏「配置」组新增入口，页内按对话 / 向量等能力分区，每项一个下拉。
- 该视图为 SPA 内页面而非独立目录：宿主侧栏对每个插件仅取 `pages[0]`，
  新建目录不会出现在侧边栏中。
- 当前值对应的模型已不存在时，保留为「⚠ xxx（已不存在）」选项，避免下拉静默回落
  至默认项而使已保存的配置被改写。
- 基础设置页中的模型项同样渲染为下拉；模型清单未就绪时回退为文本输入框，
  避免出现空白下拉。

### 向量模型可选用宿主提供商

- 新增配置项 `EMBED_PROVIDER_ID`：留空时仍使用原有的独立 Embedding 接口，行为不变。
- 选择宿主模型后，`_get_embedding` 优先调用 `EmbeddingProvider.get_embedding`，
  失败时回退至独立接口。
- 注意：更换向量模型会改变已存记忆的向量维度，旧向量无法比对，需重新向量化
  （已写入该配置项的 hint）。

### 配置分组收敛为单一来源

- 新增 `GET config/groups`。此前同一份 schema 由三套分组口径解释（`config.js` 45 组、
  `app.js` 18 组、`app.js` 11 组），任一处调整都会与其余两处产生偏差。现统一由后端下发
  8 个功能域（基础与账号 / 模型与能力 / 回复与互动 / 主动与日常 / 私信与分享 /
  人格与记忆 / 安全 / 其它）。
- 模型选择项在 schema 中的前缀并不统一（`LLM_PROVIDER_ID` 位于【人设】、
  `SCHEDULE_PLAN_PROVIDER_ID` 位于【自主安排】），仅按前缀分组会导致模型分组内容缺失，
  故这 8 个键显式归入模型组。

### 测试

- 新增 `tests/test_model_options.py`（9 条）与 `tests/test_config_groups.py`（10 条），
  覆盖启用状态过滤、类型回填、运行时合并、密钥零泄漏、单 provider 异常隔离、
  真实 schema 全键归位。

## v1.8.12 — 2026-10-27

### 自检页「最近异常」只报真异常

- **假警报口径**：`core/selftest.py` 原先把复核日志里所有 `state != visible` 的行都当「最近异常」，
  于是 90 秒那次写下的 `pending`（正常中间态）和接口层没查成的 `unverified` 都会常年挂在自检页上。
  现在 `verify_recent` 只列 `self_only` / `folded` / `invisible` / `deleted`，`unverified` 单列
  `verify_unverified`，自检页各占一行（「最近异常」/「未查成」）。
- **状态显示成中文**：`pages/bilibot/views/selftest.js` 原先把英文状态 token 原样拼进页面，
  现在映射为「仅自己可见 / 被折叠 / 前端不渲染 / 已删除 / 未查成」，未知状态原样显示。
- **日志措辞**：`_report` 把 `self_only` 与 `unverified` 混成同一句 warning，排查时分不清
  「有结论」和「没查成」；现在各附一句人话（前者「匿名查不到、登录查得到」，后者「不据此下结论」）。

### 楼中楼评论进入 LLM 语境

- `_get_hot_comments` 只取顶层评论、丢掉 `replies` 预览；现在按原顺序递归展平一楼 + 楼中楼，
  仍只打一次列表接口（每条截 100 字符、深度 ≤3），空文本与前后空白按 strip 后跳过。

### 配置说明对齐实现

- `COMMENT_VERIFY_ANONYMOUS` 的 hint 原先承诺「关掉就只做单视角」，但 `kind="reply"` 的楼中楼探测
  必须两段才判得出可见性、不受该开关影响。现在 hint 写明「关掉只影响主列表的对照」，代码处也留了注释。

### 测试

- 新增 3 条：`_report` 两种状态措辞不同 / 通过与待确认不打 warning、`_get_hot_comments` 含楼中楼预览；
  `test_selftest.py` 的异常口径用例扩到 7 种状态，并断言「最近异常」与「未查成」两个列表分开。

## v1.8.11 — 2026-10-27

### 楼中楼复核：补扫子列表 + 修正判定语义

这两处是一对缺陷：前者让正常可见的二级回复掉进兜底分支，后者的判定又是反的。只修一处仍会误报。

- **`find_reply` 不扫子列表**：原先只扫 `replies` / `top_replies` / `hots` / `top` 的**顶层**条目，
  而二级回复挂在各评论的 `replies` 下，正常可见的楼中楼永远命中不了，只能掉进 `kind="reply"`
  兜底分支。现在按原始顺序深度优先递归进 `replies`（父在前、子按列表顺序）；`replies` 为空、
  非列表、多层嵌套都能走，同一对象按 `id()` 去重，防重复扫描与自引用打转。命中的桶名带 `.sub`
  后缀（`replies.sub`、`top.upper.sub`），复核日志能直接看出是在楼中楼里找到的。
  `reply/reply` 的楼中楼查找（`_scan_list`）共用同一套递归实现。
- **兜底分支把公开回复判成「仅自己可见」**：原实现匿名 `reply/reply` 查到 `probe_item` 就判
  `state=self_only`——匿名都能查到，恰恰说明它对所有人可见。改成两段：
  1. 先匿名查：查到 → 按条目分类（折叠/不可见照旧），其余判 `visible`；
  2. 匿名查不到 → 登录视角再查：登录能看到 → `self_only`（条目自身标了折叠/不可见则保留更具体的状态）；
  3. 两段都查不到才判「没了」：只有**登录**视角的 `12022` 才算根评论没了 → `deleted`，
     其余一律留 `unverified`（不重新引入已废除的 `missing`）。
- **「查询失败」不再被当成「查不到」**（同一误判类的另外两个入口，一起堵）：
  1. 匿名楼中楼查询返回风控（`-403` / `-352` 等）/ 网络 / 结构异常 → 记 `unverified` + `error`，
     不再继续拿登录视角反推「仅自己可见」；
  2. 主列表匿名翻页失败原先被 `break` 吞掉、`code=0` 但 `data` 结构异常的响应也算「没查到」，
     两者都会走到「登录视角命中 → `self_only`」；现在 `scan_pages` 把错误冒泡、
     `_wbi_payload` 对结构异常直接报 `payload:data`，前者判 `unverified`，后者不再冒充命中。
- 新增 13 条回归测试；`test_回复用父评论当root找人` 里编码旧（错误）语义的 `self_only` 断言已改掉。

## v1.8.10 — 2026-10-27

### 修复自检发现的四处问题

- **复核丢 `type`**：`schedule_verify` 不传评论区类型，复核一律按视频（`type=1`）查。
  动态评论区（`type=17`）的评论与回复会查到错误的评论区，永远判 `unverified`。
  现在从发送处把 `oid_type` / `reply_type` 透传下去。
- **二级回复用错 root**：`kind="reply"` 的存在性探测拿「回复自己的 rpid」当 root，
  查的是它下面的子回复，永远找不到自己。现在 `_send_reply` 把被回复的父评论 rpid 传下来，
  按父评论的楼中楼找目标。
- **翻页无效**：`scan_pages` 翻页时仍带 `seek_rpid`，服务端每次都重新定位回同一页，
  `pagination offset` 形同虚设。现在翻页显式 `seek=False`；默认最多翻到第 2 页，
  异常路径请求数从 7 降到 5。
- **`WATCH_LOG_ACTIVE_CAP` 配置没被消费**：schema 有配置项，`append_watch_entry` 只读模块常量，
  用户改配置无效。现在配置优先。

### 顺带

- `check_visibility` 里永远不会走到的 `view="both"` 分支删掉（匿名命中会直接返回）。
- 新增 6 条回归测试：type 透传、翻页不带 seek、回复按父评论找自己、发送侧透传 type / 父评论、
  配置 cap 生效。

## v1.8.9 — 2026-10-27

### 归档写入幂等

- `_archive_entries` 按月追加时按 `(time, bvid)` 去重：异常重试或手工恢复同一份 watch_log 时，
  归档文件不会越攒越大。读取侧本来就去重，这里补的是冷数据本身的幂等。
- 去重键抽成 `_entry_key()`，归档与 `load_watch_entries()` 共用，避免两处规则漂移。

### 删掉废弃的 @register

- 本机内核 `Star.__init_subclass__` 已自动注册插件类（实测 `star_map` 有该类、`star_cls_type` 指向它），
  加载器随后又用 `metadata.yaml` 覆盖 name/author/desc/version/repo；所以 `@register` 既不生效、
  又让版本号出现两处（删前 `main.py` 是 1.8.7、`metadata.yaml` 是 1.8.8）。
- 删掉装饰器与 `register` 的 import；文件头 docstring 里残留的 `1.7.2` 一并清掉。
- 之后版本号只改 `metadata.yaml` 一处。
- 状态命令里的版本号也改成读 `metadata.yaml`（原先硬编码 `1.7.2`），以后只需改一处。

## v1.8.8 — 2026-10-27

### 评论复核改成 rpid 定点 + 双视角 + 两时点

- **根因**：原实现只在评论首页 20 条里找 rpid，热门视频 90 秒就能把新评论顶出首页，于是把
  「查不到」当成「没发出去」；而且只复核带 @ 的评论，普通评论被折叠/被吞没有任何信号。
- 改用 `x/v2/reply/wbi/main` + `seek_rpid` 定点定位（`mode=2` 仅按时间），命中范围扫
  `replies` / `top` / `top_replies` / `hots`。
- 90 秒只做「乐观确认」；查不到记 `pending`，10 分钟后用**匿名 + 登录双视角**判定：
  匿名查不到、登录查得到 = `self_only`（仅自己可见）。两视角都空才用 `reply/reply` 探测，
  登录视角也 12022 才判 `deleted`。
- 状态从 3 个扩到 7 个，`missing` 语义废除；接口层失败一律 `unverified`，不再冒充「被吞」。
- 所有成功发出的评论与回复都复核（不再只限带 @）。

### 修 WBI 签名：参数含 JSON 时必失败

- `sign_wbi_params` 缺两步标准处理：参数值里 `!'()*` 过滤、`urlencode` 后再拼串。
  参数含 JSON（如 `pagination_str`）时签名与服务端不一致，`wbi/main` 实测返回 `-403`。
- 修正后同一请求返回 `code=0`；搜索接口回归验证 `code=0`。

### watch_log 改按月归档

- 写入侧不再硬截断 200 条：主文件保留最近 500 条（`WATCH_LOG_ACTIVE_CAP`），溢出的按月写
  `data/watch_log_archive/YYYY-MM.json`；读取侧 `load_watch_entries()` 合并归档 + 主文件。
- 归档失败时**不裁剪**主文件，不丢记录。
- 修掉 `_save_json(WATCH_LOG_FILE, watch_log[-200:])` 这个会砍掉主文件多余条目的回写方式。
- 卡片墙、历史详情、自检计数改读全量。

### 新增收藏夹投喂池

- 配置 `PROACTIVE_FAV_FOLDERS`：支持 media_id 或带 `fid=` 的收藏夹链接。
- 新来源 `fav` 在配额顺序里排第一；失效视频（`attr != 0`）自动跳过。

## v1.8.7 — 2026-10-25

### 私信失败的真因：DEDE_USER_ID 没填

- **现象**：点「测私信」失败，界面提示「Cookie 失效 / 对方关闭私信 / 风控」——全指向错方向。
- **真因**：`_send_bili_private_payload` 要求 `msg[sender_uid]`（发送者 UID，取自 `DEDE_USER_ID`）
  必须是数字；本机这项为空，函数在发请求**之前**就 `return False`。
- **修法**：`DEDE_USER_ID` 不合法时，从 nav 接口自动识别自己的 UID（只缓存到实例，不回写配置）。
  实测本机 Cookie 有效、Bot 是 Fireflybb（UID `3747574768994456`），与主人 `1215576595` 不同号。
- 「测私信」加前置检查：Cookie 不可用或缺 `BILI_JCT` 时直接给准确原因，不再落到笼统的「发送失败」。
- 失败提示补上「检查 DEDE_USER_ID」这条线索。

### 已知限制

若 Bot 账号与主人是**同一个号**，B站 会拒发（sender == receiver 被主动拦下），需要两个号才能测私信。
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
