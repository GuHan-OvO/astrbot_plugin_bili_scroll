// 从 pages/selftest/ 迁移来的「自检」SPA 视图模块。
//
// 原来这是一个由 AstrBot 宿主用 iframe 单独加载的页面：index.html 用 <link> 引 style.css、
// <script type="module"> 引 app.js，整个 document 归它独占。现在要放进控制中心 SPA 的
// #content 里当一个内页，所以用 Shadow DOM 做隔离：
//   1. style.css 全文内联进 shadow 内的 <style>（不用 <link>：宿主会重写资源 URL，
//      动态插进去的 link 拿不到 asset_token，会 403）；
//   2. 样式只作用于 shadow 树，不污染 SPA 的全局样式；
//   3. 元素查询全部落在 shadow 内（document.getElementById → shadow.querySelector），
//      模块不访问 host 之外的 DOM 节点。
//
// CSS 适配只动选择器：:root 在 shadow 内不生效，改成 :host（--* 自定义属性定义在宿主
// 元素上，shadow 内的元素照常继承）；html / body 这两层盒子在 shadow 里不存在，同样
// 塌缩成 :host。其余选择器、类名、变量名一律保持原样（shadow 内天然隔离，不会冲突）。
// JS 只把取元素换成 shadow 查询，初始化顺序、渲染、POST trial 的语义都不变。

const STYLE = `
/* 「自检」页面。
 * 视觉令牌不在 shadow 内重抄：自定义属性从宿主继承，控制中心换主题时这一页跟着走。
 * 这里只补宿主没有的别名。
 */
:host {
  color-scheme: light;
  --text-2: var(--text-secondary);
  --text-3: var(--text-tertiary);
  --font: var(--font-ui);
  --ambient: var(--accent-soft);
}

/* 深浅色只跟控制中心的 data-theme：控制中心是手动切换的，如果这里再留一份
   @media (prefers-color-scheme: dark)，用户手动切到浅色时会被系统深色压回去。
   bilibot/app.js 的 applyTheme() 会把解析后的主题写到 [data-embedded-view] 上。 */
:host([data-theme="dark"]) {
  /* 原生控件（select 弹层、滚动条）按这个走，否则手动切深色后它们还是浅色 */
  color-scheme: dark;
}

*,
*::before,
*::after {
  box-sizing: border-box;
}

:host {
  /* 原 html 规则：底色挂在宿主元素上，.ambient 才能用 z-index:-1 画在正文之下。
     下面的 body 规则也塌缩成 :host，会以 background: transparent 覆盖本条，
     与独立页面「画布给底色、body 透明」的分层一致。 */
  background: var(--bg);
}

:host {
  margin: 0;
  /* 独立页面时这里是 100vh（撑满视口）；作为 SPA 内页由 #content 决定高度，不需要再撑一屏 */
  min-height: 0;
  background: transparent;
  color: var(--text);
  font-family: var(--font);
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

h1,
h2,
h3,
p,
dl,
dd {
  margin: 0;
}

ul,
ol {
  margin: 0;
  padding: 0;
  list-style: none;
}

button {
  border: 0;
  background: none;
  font: inherit;
  color: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.ambient {
  /* 控制中心外壳自己已经有背景光晕（design/base.css），内页再铺一层会叠色，这里关掉 */
  display: none;
  position: fixed;
  inset: 0;
  z-index: -1;
  overflow: hidden;
  pointer-events: none;
  background: radial-gradient(120% 70% at 50% -20%, var(--ambient) 0%, transparent 62%), var(--bg);
}

.ambient span {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.7;
}

.ambient span:first-child {
  top: -12vh;
  left: -8vw;
  width: 44vw;
  height: 44vw;
  background: var(--ambient);
  animation: drift 28s var(--ease-out) infinite alternate;
}

.ambient span:last-child {
  right: -10vw;
  bottom: -20vh;
  width: 36vw;
  height: 36vw;
  background: var(--accent-soft);
  animation: drift 34s var(--ease-out) infinite alternate-reverse;
}

@keyframes drift {
  to {
    transform: translate3d(4vw, 5vh, 0) scale(1.14);
  }
}

.page {
  /* 外层 #content 已经给了最大宽度和左右内边距，这里不再叠一层，只留底部留白 */
  max-width: none;
  margin: 0;
  padding: 0 0 32px;
}

/* ── 页头 ───────────────────────────────────────────────────────────── */

.page-bar {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.bar-copy {
  flex: 1 1 min(420px, 100%);
  min-width: 0;
}

.eyebrow {
  display: inline-block;
  margin-bottom: 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--text-3);
}

.page-bar h1 {
  font-size: clamp(24px, 3vw, 32px);
  line-height: 1.12;
  font-weight: 600;
  letter-spacing: -0.026em;
  color: var(--text-strong);
}

.bar-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--text-2);
}

.bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.stamp {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}

/* ── 按钮 ───────────────────────────────────────────────────────────── */

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  padding: 0 16px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-pill);
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out), transform 90ms var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.btn:hover {
  border-color: color-mix(in srgb, var(--text) 24%, transparent);
  box-shadow: var(--shadow-1);
  transform: translateY(-1px);
}

.btn:active {
  transform: scale(0.972);
}

.btn.soft {
  border-color: transparent;
  background: var(--surface-sunken);
  color: var(--text-2);
}

.btn.soft:hover {
  color: var(--text);
}

.btn.primary {
  border-color: transparent;
  background: var(--accent);
  color: #fff;
}

.btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* ── 卡片网格 ───────────────────────────────────────────────────────── */

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.card {
  padding: 18px 20px 20px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow-1);
  animation: cardIn var(--dur-slow) var(--ease-out) both;
  transition: border-color var(--dur-base) var(--ease-out), box-shadow var(--dur-base) var(--ease-out);
}

.card.wide {
  grid-column: 1 / -1;
  margin-top: 16px;
}

.card:nth-child(2) {
  animation-delay: 30ms;
}

.card:nth-child(3) {
  animation-delay: 60ms;
}

.card:nth-child(4) {
  animation-delay: 90ms;
}

@keyframes cardIn {
  from {
    opacity: 0;
    transform: translate3d(0, 10px, 0);
  }
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--line);
}

.card-head h2 {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-strong);
}

.dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-3);
  opacity: 0.5;
}

.dot.idle {
  background: var(--text-3);
  opacity: 0.5;
}

.dot.ok {
  background: var(--green);
  opacity: 1;
  box-shadow: 0 0 0 3px var(--green-soft);
}

.dot.bad {
  background: var(--red);
  opacity: 1;
  box-shadow: 0 0 0 3px var(--red-soft);
}

.note {
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-3);
}

/* ── 键值表 ─────────────────────────────────────────────────────────── */

.kv {
  display: grid;
  grid-template-columns: minmax(72px, auto) minmax(0, 1fr);
  gap: 6px 14px;
  font-size: 13px;
}

.kv dt {
  padding-top: 1px;
  font-size: 12px;
  color: var(--text-3);
}

.kv dd {
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  color: var(--text);
  word-break: break-word;
}

.kv dd.ok-text {
  color: var(--green);
}

.kv dd.bad-text {
  color: var(--red);
}

/* ── 勾选列表 ───────────────────────────────────────────────────────── */

.checks {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.checks li {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 6px 0;
  font-size: 13px;
}

.checks li + li {
  border-top: 1px solid var(--line);
}

.checks li > div {
  min-width: 0;
}

.checks .name {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 500;
  color: var(--text);
}

.checks .hint {
  color: var(--text-3);
  font-size: 12px;
}

.checks .hint.bad-text {
  color: var(--red);
}

.checks li.hint {
  font-size: 12px;
  color: var(--text-3);
}

/* 折叠的可选配置 */
.fold {
  padding-top: 10px;
  margin-top: 12px;
  border-top: 1px solid var(--line);
}

.fold > summary {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  list-style: none;
  transition: color var(--dur-fast) var(--ease-out);
}

.fold > summary::-webkit-details-marker {
  display: none;
}

.fold > summary::before {
  content: "›";
  display: inline-block;
  font-size: 14px;
  line-height: 1;
  color: var(--text-3);
  transition: transform var(--dur-base) var(--ease-apple);
}

.fold[open] > summary::before {
  transform: rotate(90deg);
}

.fold > summary:hover {
  color: var(--text);
}

.fold > dl {
  margin-top: 10px;
  animation: cardIn var(--dur-base) var(--ease-out) both;
}

.sub-head {
  margin: 18px 0 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
}

.error {
  padding: 14px 16px;
  margin-bottom: 16px;
  border: 1px solid color-mix(in srgb, var(--red) 30%, transparent);
  border-radius: var(--r-md);
  background: var(--red-soft);
  color: var(--red);
  font-size: 13px;
}

@media (max-width: 560px) {
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .bar-actions {
    width: 100%;
    justify-content: flex-end;
  }

  /* 触屏下把控件抬到 44px：桌面 36px 的可点目标在手机上偏小 */
  .btn {
    height: 44px;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }

  .ambient span {
    animation: none !important;
  }
}
`;

const MARKUP = `
  <div class="ambient" aria-hidden="true"><span></span><span></span></div>

  <div class="page">
    <header class="page-bar">
      <div class="bar-copy">
        <span class="eyebrow">BILIBOT / SELF CHECK</span>
        <h1>自检</h1>
        <p class="bar-sub">只读检查模块、配置、数据与路由；下方「刷一个 / 测私信 / 测提及」会真实向 B站 发出请求。</p>
      </div>
      <div class="bar-actions">
        <span id="stamp" class="stamp"></span>
        <button id="reload" class="btn soft" type="button">重新检查</button>
        <button id="trial" class="btn primary" type="button">刷一个</button>
        <button id="test-private" class="btn soft" type="button">测私信</button>
        <button id="test-mention" class="btn soft" type="button">测提及</button>
      </div>
    </header>

    <p id="error" class="error" hidden></p>

    <main id="root" class="grid">
      <section class="card" id="card-module">
        <header class="card-head"><span class="dot idle"></span><h2>模块</h2></header>
        <dl id="module-list" class="kv"></dl>
      </section>

      <section class="card" id="card-config">
        <header class="card-head"><span class="dot idle"></span><h2>配置</h2></header>
        <p class="note" id="config-total"></p>
        <ul id="config-required" class="checks"></ul>
        <details class="fold">
          <summary>可选配置</summary>
          <dl id="config-optional" class="kv"></dl>
        </details>
      </section>

      <section class="card" id="card-data">
        <header class="card-head"><span class="dot idle"></span><h2>数据</h2></header>
        <dl id="data-list" class="kv"></dl>
      </section>

      <section class="card" id="card-pages">
        <header class="card-head"><span class="dot idle"></span><h2>页面与路由</h2></header>
        <dl id="route-list" class="kv"></dl>
        <ul id="page-list" class="checks"></ul>
      </section>
    </main>

    <section class="card wide" id="card-trial" hidden>
      <header class="card-head"><span class="dot idle"></span><h2>试运行</h2></header>
      <p class="note" id="trial-note"></p>
      <dl id="trial-cookie" class="kv"></dl>
      <h3 class="sub-head">细节</h3>
      <ul id="trial-candidates" class="checks"></ul>
    </section>
  </div>
`;

export function mountSelftest(host) {
  const shadow = host.shadowRoot || host.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>${STYLE}</style>${MARKUP}`;

  // 自检页面。数据来自 GET selftest，返回结构见 core/selftest.py::collect。
  // 所有文本用 textContent 写入，不拼 HTML。
  const bridge = window.AstrBotPluginPage || null;

  const el = {
    root: shadow.querySelector("#root"),
    error: shadow.querySelector("#error"),
    reload: shadow.querySelector("#reload"),
    stamp: shadow.querySelector("#stamp"),
    moduleList: shadow.querySelector("#module-list"),
    configTotal: shadow.querySelector("#config-total"),
    configRequired: shadow.querySelector("#config-required"),
    configOptional: shadow.querySelector("#config-optional"),
    dataList: shadow.querySelector("#data-list"),
    routeList: shadow.querySelector("#route-list"),
    pageList: shadow.querySelector("#page-list"),
    trial: shadow.querySelector("#trial"),
    testPrivate: shadow.querySelector("#test-private"),
    testMention: shadow.querySelector("#test-mention"),
    trialCard: shadow.querySelector("#card-trial"),
    trialNote: shadow.querySelector("#trial-note"),
    trialCookie: shadow.querySelector("#trial-cookie"),
    trialCandidates: shadow.querySelector("#trial-candidates"),
  };

  // 切页后 stop 轮询与倒计时：视图销毁后仍在写已脱离文档的 DOM 是明确的泄漏。
  let destroyed = false;

  const cards = {
    module: shadow.querySelector("#card-module"),
    config: shadow.querySelector("#card-config"),
    data: shadow.querySelector("#card-data"),
    pages: shadow.querySelector("#card-pages"),
  };

  function unwrap(result) {
    if (result && result.status === "ok" && Object.prototype.hasOwnProperty.call(result, "data")) {
      return result.data;
    }
    if (result && result.status === "error") throw new Error(result.message || "请求失败");
    return result?.data ?? result ?? {};
  }

  async function apiPost(path, body = {}) {
    if (!bridge) throw new Error("这个页面需要在 AstrBot 里打开（缺少插件页面桥）");
    if (typeof bridge.apiPost !== "function") throw new Error("当前页面桥不支持 POST");
    return unwrap(await bridge.apiPost(path, body));
  }

  async function apiGet(path, query = {}) {
    if (!bridge) throw new Error("这个页面需要在 AstrBot 里打开（缺少插件页面桥）");
    return unwrap(await bridge.apiGet(path, query));
  }

  function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function clear(target) {
    target.replaceChildren();
  }

  function markCard(card, tone) {
    const dot = card?.querySelector(".dot");
    if (!dot) return;
    dot.classList.remove("ok", "bad", "idle");
    dot.classList.add(tone);
    // 状态点原先只有颜色：给读屏与色觉障碍一个文本结论。
    const label = { ok: "正常", bad: "异常", idle: "未知" }[tone] || "未知";
    dot.setAttribute("role", "img");
    dot.setAttribute("aria-label", label);
    card.dataset.state = label;
  }

  function addRow(dl, label, value, tone) {
    dl.appendChild(node("dt", null, label));
    const text = value === undefined || value === null || value === "" ? "—" : value;
    const dd = node("dd", tone || null, text);
    dl.appendChild(dd);
    return dd;
  }

  function renderModule(info) {
    clear(el.moduleList);
    if (!info) {
      markCard(cards.module, "bad");
      return addRow(el.moduleList, "状态", "读取失败", "bad-text");
    }
    markCard(cards.module, "ok");
    addRow(el.moduleList, "包名", info.plugin_name);
    addRow(el.moduleList, "插件目录", info.plugin_root);
    addRow(el.moduleList, "数据目录", info.data_dir);
    addRow(el.moduleList, "Python", info.python);
    addRow(el.moduleList, "解释器", info.executable);
  }

  function renderMetadata(meta) {
    if (!meta) return;
    addRow(el.moduleList, "显示名", meta.display_name);
    addRow(el.moduleList, "版本", meta.version);
    addRow(el.moduleList, "作者", meta.author);
    // repo 为空说明不跟随市场更新，这是预期状态
    addRow(el.moduleList, "追踪上游", meta.repo ? meta.repo : "否（repo 为空）");
  }

  function renderConfig(cfg) {
    clear(el.configRequired);
    if (!cfg) {
      el.configTotal.textContent = "读取失败";
      markCard(cards.config, "bad");
      return;
    }    const required = cfg.required || [];
    const allOk = required.every((item) => item.ok);
    markCard(cards.config, allOk ? "ok" : "bad");
    el.configTotal.textContent = `配置项共 ${cfg.total_keys} 个${allOk ? "" : " · 有必填项未通过"}`;

    for (const item of required) {
      const li = node("li");
      li.appendChild(node("span", `dot ${item.ok ? "ok" : "bad"}`));
      const body = node("div");
      body.appendChild(node("span", "name", item.key));
      body.appendChild(node("span", "hint", `　${item.detail}　·　${item.hint}`));
      li.appendChild(body);
      el.configRequired.appendChild(li);
    }

    clear(el.configOptional);
    for (const item of cfg.optional || []) {
      // 后端会把未配置项的值原样传成 None：直接插模板会渲染出 "null"。
      addRow(el.configOptional, item.key, `${item.value ?? "—"}　（${item.hint ?? "—"}）`);
    }
  }

  // 复核状态 → 中文；未知状态原样显示（别吞掉后端新加的状态）
  const VERIFY_STATE_LABELS = {
    visible: "可见",
    self_only: "仅自己可见",
    folded: "被折叠",
    invisible: "前端不渲染",
    deleted: "已删除",
    pending: "待确认",
    unverified: "未查成",
  };

  function verifyStateText(state) {
    return VERIFY_STATE_LABELS[state] || state || "—";
  }

  function renderData(data, pages) {
    clear(el.dataList);
    if (!data) {
      markCard(cards.data, "bad");
      return addRow(el.dataList, "状态", "读取失败", "bad-text");
    }
    const watch = data.watch_log || {};
    const verify = data.verify_log || {};
    const db = data.database || {};
    const broken = watch.count == null || verify.count == null;
    markCard(cards.data, broken ? "bad" : "ok");

    addRow(
      el.dataList,
      "看过的视频",
      watch.count == null ? "文件损坏" : `${watch.total ?? watch.count} 条`
    );
    addRow(el.dataList, "复核记录", verify.count == null ? "文件损坏" : `${verify.count} 条`);
    const verifyRecent = data.verify_recent || [];
    addRow(
      el.dataList,
      "最近异常",
      verifyRecent.length
        ? verifyRecent.map((row) => `${verifyStateText(row.state)} ${row.rpid}`).join("；")
        : "无"
    );
    // pending 是正常中间态、unverified 是没查成，都不算异常；这里单列一行，
    // 免得常态噪声把「最近异常」里真出问题的行淹掉。
    const verifyUnverified = data.verify_unverified || [];
    addRow(
      el.dataList,
      "未查成",
      verifyUnverified.length
        ? verifyUnverified.map((row) => `${verifyStateText(row.state)} ${row.rpid}`).join("；")
        : "无"
    );
    addRow(el.dataList, "数据库", db.exists ? `存在（${Math.round((db.size || 0) / 1024)} KB）` : "尚未创建");
    addRow(el.dataList, "页面目录", `${(pages || []).length} 个`);
  }

  function renderRoutes(routes, pages) {
    clear(el.routeList);
    if (!routes) {
      markCard(cards.pages, "bad");
      return addRow(el.routeList, "状态", "读取失败", "bad-text");
    }
    markCard(cards.pages, (pages || []).length ? "ok" : "bad");
    addRow(el.routeList, "路由前缀", routes.prefix);
    for (const example of routes.examples || []) {
      addRow(el.routeList, "示例", example);
    }

    clear(el.pageList);
    for (const page of pages || []) {
      const li = node("li");
      li.appendChild(node("span", "dot ok"));
      li.appendChild(node("span", "name", page.name));
      el.pageList.appendChild(li);
    }
    if (!pages || !pages.length) {
      el.pageList.appendChild(node("li", "hint", "没有找到页面目录"));
    }
  }


  /* 防连点：冷却期禁用按钮，剩余秒数放提示行（按钮文字保持 4 字以内）。 */
  let cooldownTimer = 0;

  function syncCooldown(remaining, options = {}) {
    window.clearInterval(cooldownTimer);
    let left = Number(remaining) || 0;
    if (left <= 0) {
      el.trial.disabled = false;
      el.trial.title = "";
      return;
    }
    el.trial.disabled = true;
    el.trial.title = `冷却中，还要等 ${left} 秒`;
    // keepNote：真跑刚结束时 note 里是「刷完了，用时 X 秒」这类结论，
    // 冷却倒计时只写按钮 title，不能把结论覆盖成「冷却中」。
    if (!options.keepNote) el.trialNote.textContent = `冷却中，还要等 ${left} 秒`;
    cooldownTimer = window.setInterval(() => {
      left -= 1;
      el.trial.title = left > 0 ? `冷却中，还要等 ${left} 秒` : "";
      if (left <= 0) {
        window.clearInterval(cooldownTimer);
        el.trial.disabled = false;
        if (!options.keepNote) el.trialNote.textContent = "";
        return;
      }
      if (!options.keepNote) el.trialNote.textContent = `冷却中，还要等 ${left} 秒`;
    }, 1000);
  }

  /* 问后端当前是否在冷却——状态在后端，刷新页面也拦得住。 */
  async function refreshCooldown(options = {}) {
    try {
      const state = await apiGet("trial/live");
      syncCooldown(state && state.cooldown_remaining, options);
    } catch (err) {
      syncCooldown(0, options);
    }
  }


  /* 单独测私信 / 真 @。两者都会真的往 B站 发东西，后端有 30 秒共用冷却。 */
  const TEST_LABEL = { private: "测私信", mention: "测提及" };

  async function runTest(kind) {
    const btn = kind === "private" ? el.testPrivate : el.testMention;
    const label = TEST_LABEL[kind];
    // 上一次冷却留下的 1s 倒计时会在接下来几秒里继续写 note，把本次结果覆盖掉。
    window.clearInterval(cooldownTimer);
    btn.disabled = true;
    btn.textContent = "发送中…";
    el.trialCard.hidden = false;
    markCard(el.trialCard, "idle");
    el.trialNote.textContent =
      kind === "private" ? "正在发私信…" : "正在最近看过的视频下发带 @ 的评论…";
    try {
      renderTestResult(await apiPost("trial/test", { kind }));
    } catch (err) {
      markCard(el.trialCard, "bad");
      el.trialNote.textContent = `${label}失败：${err?.message || err}`;
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  function renderTestResult(res) {
    clear(el.trialCookie);
    clear(el.trialCandidates);

    const cooldown = Number(res && res.retry_after) || 0;
    if (cooldown > 0) {
      markCard(el.trialCard, "idle");
      el.trialNote.textContent = res.error || "冷却中";
      return;
    }

    const ok = !!(res && res.ok);
    const isPrivate = (res && res.kind) === "private";
    markCard(el.trialCard, ok ? "ok" : "bad");
    el.trialNote.textContent = ok
      ? isPrivate
        ? "私信已发出，去 B站 消息里看看"
        : "带 @ 的评论已发出，等推送到达"
      : (res && res.error) || "失败";

    // 后端成功响应没有 error 字段；原先按 error === undefined 直接 return，
    // 导致「测私信 / 测提及」成功时收件人、内容、oid、@映射全部不显示。
    if (!res) return;

    if (isPrivate) {
      addRow(el.trialCookie, "收件人",
        res.target_name ? `${res.target_name}（${res.target_mid}）` : String(res.target_mid || "—"),
        ok ? "ok-text" : "");
      addRow(el.trialCookie, "内容", res.text || "—");
    } else if (res.bvid) {
      addRow(el.trialCookie, "视频", res.bvid);
      addRow(el.trialCookie, "oid", String(res.oid || "—"));
      const map = res.at_map || {};
      const mapped = Object.keys(map).length > 0;
      addRow(el.trialCookie, "@映射",
        mapped ? JSON.stringify(map) : "空（只能发纯文本 @，B站 不会推送）",
        mapped ? "ok-text" : "bad-text");
      addRow(el.trialCookie, "评论", res.text || "—");
    }

    if (!ok && res.detail) {
      el.trialCandidates.appendChild(node("li", "hint", res.detail));
    }
  }


  async function runTrial() {
    // 同 runTest：先停掉旧的冷却倒计时，避免它每秒把「刷完了」覆盖成「冷却中」。
    window.clearInterval(cooldownTimer);
    el.trial.disabled = true;
    el.trial.textContent = "刷片中…";
    el.error.hidden = true;
    el.trialCard.hidden = false;
    markCard(el.trialCard, "idle");
    el.trialNote.textContent = "正在刷 B站：取片 → 分析 → 评价 → 按配置互动。可能要一两分钟…";
    let produced = false;
    try {
      const started = await apiPost("trial/live");
      if (!started || !started.started) {
        el.trialNote.textContent = (started && started.reason) || "启动失败";
        syncCooldown((started && started.retry_after) || 0);
        produced = true;
        return;
      }
      renderLive(await pollLive());
      produced = true;
    } catch (err) {
      if (destroyed) return;
      el.trialCard.hidden = false;
      markCard(el.trialCard, "bad");
      el.error.hidden = false;
      el.error.textContent = `刷片失败：${err?.message || err}`;
    } finally {
      el.trial.disabled = false;
      el.trial.textContent = "刷一个";
      // 拿到结论时别让冷却倒计时覆盖它：冷却只写按钮 title 与禁用状态。
      if (!destroyed) await refreshCooldown({ keepNote: produced });
    }
  }

  /* 轮询真跑状态。一次可能一两分钟，所以每 2 秒问一次，最多等 6 分钟。 */
  async function pollLive() {
    const deadline = Date.now() + 6 * 60 * 1000;
    let last = null;
    while (!destroyed && Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      if (destroyed) return last || { running: false, error: "页面已关闭", elapsed_ms: 0, watched: null };
      const state = await apiGet("trial/live");
      last = state;
      if (state && !state.running) return state;
      const secs = Math.round(((state && state.elapsed_ms) || 0) / 1000);
      el.trialNote.textContent = `正在刷片… 已 ${secs} 秒`;
    }
    return last || { running: false, error: "等待超时", elapsed_ms: 0, watched: null };
  }

  /* 真跑结果：这一轮到底看了哪个视频、给了几分、动了什么手。 */
  function renderLive(state) {
    el.trialCard.hidden = false;
    const secs = Math.round(((state && state.elapsed_ms) || 0) / 1000);
    const watched = (state && state.watched) || null;
    const failed = !!(state && state.error);

    markCard(el.trialCard, failed ? "bad" : watched ? "ok" : "idle");
    el.trialNote.textContent = failed
      ? `刷片出错：${state.error}`
      : watched
        ? `刷完了，用时 ${secs} 秒`
        : `跑完了，用时 ${secs} 秒，但这一轮没有看成任何视频（可能全部被跳过）`;

    clear(el.trialCookie);
    clear(el.trialCandidates);

    if (!watched) return;

    addRow(el.trialCookie, "视频", watched.title || watched.bvid);
    addRow(el.trialCookie, "UP", watched.up_name);
    addRow(
      el.trialCookie,
      "评分",
      watched.failed ? "评价失败" : `${watched.score ?? "—"} / 10`,
      watched.failed ? "bad-text" : ""
    );
    addRow(el.trialCookie, "心情", watched.mood);
    addRow(el.trialCookie, "时间", watched.time);
    addRow(
      el.trialCookie,
      "动作",
      Array.isArray(watched.actions) && watched.actions.length ? watched.actions.join(" / ") : "无（未触发互动）"
    );

    for (const [label, value] of [
      ["它说的", watched.review || watched.comment],
      ["为什么", watched.score_reason],
    ]) {
      if (!value) continue;
      const li = node("li");
      li.appendChild(node("span", "hint", `${label}：${value}`));
      el.trialCandidates.appendChild(li);
    }
  }

  async function load() {
    el.reload.disabled = true;
    el.reload.textContent = "检查中…";
    el.error.hidden = true;
    try {
      const data = await apiGet("selftest");
      renderModule(data.module);
      renderMetadata(data.metadata);
      renderConfig(data.config);
      renderData(data.storage, data.pages);
      renderRoutes(data.routes, data.pages);

      if (Array.isArray(data.errors) && data.errors.length) {
        el.error.hidden = false;
        el.error.textContent = `部分区块读取失败：${data.errors.join("；")}`;
      }
      el.stamp.textContent = `检查于 ${new Date().toLocaleTimeString("zh-CN")}`;
    } catch (err) {
      el.error.hidden = false;
      el.error.textContent = `读取失败：${err?.message || err}`;
      Object.values(cards).forEach((card) => markCard(card, "bad"));
    } finally {
      el.reload.disabled = false;
      el.reload.textContent = "重新检查";
    }
  }

  const onTestPrivate = () => runTest("private");
  const onTestMention = () => runTest("mention");
  el.reload.addEventListener("click", load);
  el.trial.addEventListener("click", runTrial);
  el.testPrivate.addEventListener("click", onTestPrivate);
  el.testMention.addEventListener("click", onTestMention);
  refreshCooldown();

  // 原页面会在这里改写 <meta name="theme-color">。那个 meta 属于宿主 SPA 外壳、
  // 由 bilibot/app.js 维护，内嵌视图不该去改它，所以这段监听直接去掉（不留空转回调）。

  if (bridge?.ready) {
    Promise.resolve(bridge.ready()).then(load).catch(() => load());
  } else {
    load();
  }

  return {
    destroy() {
      destroyed = true;
      window.clearInterval(cooldownTimer);
      el.reload.removeEventListener("click", load);
      el.trial.removeEventListener("click", runTrial);
      el.testPrivate.removeEventListener("click", onTestPrivate);
      el.testMention.removeEventListener("click", onTestMention);
    },
  };
}
