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
/* 「自检」页面。与控制中心共用同一套视觉令牌，但文件自包含。 */

:host {
  color-scheme: light;

  --bg: #f5f5f7;
  --surface: #ffffff;
  --surface-muted: #fafafc;
  --surface-sunken: #f1f1f4;
  --text: #1d1d1f;
  --text-strong: #000000;
  --text-2: #6e6e73;
  --text-3: #8e8e93;
  --line: rgba(0, 0, 0, 0.08);
  --line-strong: rgba(0, 0, 0, 0.14);
  --accent: #0071e3;
  --accent-soft: rgba(0, 113, 227, 0.09);
  --green: #1f8a3d;
  --green-soft: rgba(52, 199, 89, 0.14);
  --orange: #b35c00;
  --orange-soft: rgba(255, 149, 0, 0.16);
  --red: #c9302c;
  --red-soft: rgba(255, 59, 48, 0.11);
  --shadow-1: 0 1px 2px rgba(16, 24, 40, 0.045);
  --shadow-2: 0 14px 34px -18px rgba(16, 24, 40, 0.24), 0 2px 6px rgba(16, 24, 40, 0.04);
  --r-sm: 9px;
  --r-md: 13px;
  --r-lg: 18px;
  --r-pill: 999px;
  --dur-fast: 150ms;
  --dur-base: 220ms;
  --dur-slow: 320ms;
  --ease-out: cubic-bezier(0.22, 0.68, 0.36, 1);
  --ease-apple: cubic-bezier(0.32, 0.72, 0, 1);
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI",
    "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", system-ui,
    sans-serif;
  --font-mono: "SF Mono", "Cascadia Mono", ui-monospace, Consolas, monospace;
  --ambient: rgba(0, 113, 227, 0.1);
}

/* 深浅色只跟控制中心的 data-theme：控制中心是手动切换的，如果这里再留一份
   @media (prefers-color-scheme: dark)，用户手动切到浅色时会被系统深色压回去。
   bilibot/app.js 的 applyTheme() 会把解析后的主题写到 [data-embedded-view] 上。 */
:host([data-theme="dark"]) {
  /* 原生控件（select 弹层、滚动条）按这个走，否则手动切深色后它们还是浅色 */
  color-scheme: dark;
  --bg: #0b0b0d;
  --surface: #1a1a1d;
  --surface-muted: #161618;
  --surface-sunken: #101012;
  --text: #f5f5f7;
  --text-strong: #ffffff;
  --text-2: #a1a1a6;
  --text-3: #7c7c82;
  --line: rgba(255, 255, 255, 0.1);
  --line-strong: rgba(255, 255, 255, 0.18);
  --accent: #0a84ff;
  --accent-soft: rgba(10, 132, 255, 0.16);
  --green: #30d158;
  --green-soft: rgba(48, 209, 88, 0.16);
  --orange: #ff9f0a;
  --orange-soft: rgba(255, 159, 10, 0.16);
  --red: #ff453a;
  --red-soft: rgba(255, 69, 58, 0.16);
  --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.5);
  --shadow-2: 0 16px 38px -20px rgba(0, 0, 0, 0.8);
  --ambient: rgba(10, 132, 255, 0.16);
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
        <p class="bar-sub">看这个插件现在到底能不能跑。只读，不会发任何 B站 请求。</p>
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
      <h3 class="sub-head">候选</h3>
      <ul id="trial-candidates" class="checks"></ul>
      <h3 class="sub-head">正式跑会做什么</h3>
      <ul id="trial-plan" class="checks"></ul>
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
    trialPlan: shadow.querySelector("#trial-plan"),
  };

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
    }
    const required = cfg.required || [];
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
      addRow(el.configOptional, item.key, `${item.value}　（${item.hint}）`);
    }
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
    const broken = watch.count === null || verify.count === null;
    markCard(cards.data, broken ? "bad" : "ok");

    addRow(el.dataList, "看过的视频", watch.count === null ? "文件损坏" : `${watch.count} 条`);
    addRow(el.dataList, "复核记录", verify.count === null ? "文件损坏" : `${verify.count} 条`);
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

  function renderTrial(data) {
    el.trialCard.hidden = false;
    markCard(el.trialCard, data.plan?.proactive_enabled ? "ok" : "idle");

    const ms = data.elapsed_ms;
    el.trialNote.textContent = `耗时 ${ms} ms · 取到 ${data.candidate_total ?? 0} 个候选 · 没有发出任何写请求`;

    clear(el.trialCookie);
    const cookie = data.cookie || {};
    addRow(el.trialCookie, "登录态", cookie.detail || "—", cookie.ok ? "ok-text" : "bad-text");

    clear(el.trialCandidates);
    const list = data.candidates || [];
    if (!list.length) {
      el.trialCandidates.appendChild(node("li", "hint", "没有取到候选（检查视频池配置或网络）"));
    }
    for (const item of list) {
      const li = node("li");
      li.appendChild(node("span", `dot ${item.source ? "ok" : "idle"}`));
      const body = node("div");
      body.appendChild(node("span", "name", item.title || item.bvid));
      const meta = [item.up_name, item.tname, item.play && `${item.play} 播放`, item.source]
        .filter(Boolean)
        .join(" · ");
      body.appendChild(node("span", "hint", `　${meta}`));
      li.appendChild(body);
      el.trialCandidates.appendChild(li);
    }

    clear(el.trialPlan);
    const plan = data.plan || {};
    if (!plan.proactive_enabled) {
      const li = node("li");
      li.appendChild(node("span", "dot bad"));
      li.appendChild(node("span", "hint bad-text", "ENABLE_PROACTIVE 关着，正式跑也不会启动"));
      el.trialPlan.appendChild(li);
    }
    for (const action of plan.actions || []) {
      const li = node("li");
      li.appendChild(node("span", `dot ${action.enabled ? "ok" : "idle"}`));
      li.appendChild(
        node(
          "span",
          "hint",
          action.enabled ? `${action.action}：评分 ≥ ${action.threshold}` : `${action.action}：已关闭`
        )
      );
      el.trialPlan.appendChild(li);
    }
    if (plan.note) el.trialPlan.appendChild(node("li", "hint", plan.note));
  }

  /* 防连点：冷却期禁用按钮，剩余秒数放提示行（按钮文字保持 4 字以内）。 */
  let cooldownTimer = 0;

  function syncCooldown(remaining) {
    window.clearInterval(cooldownTimer);
    let left = Number(remaining) || 0;
    if (left <= 0) {
      el.trial.disabled = false;
      return;
    }
    el.trial.disabled = true;
    el.trialNote.textContent = `冷却中，还要等 ${left} 秒`;
    cooldownTimer = window.setInterval(() => {
      left -= 1;
      if (left <= 0) {
        window.clearInterval(cooldownTimer);
        el.trial.disabled = false;
        el.trialNote.textContent = "";
        return;
      }
      el.trialNote.textContent = `冷却中，还要等 ${left} 秒`;
    }, 1000);
  }

  /* 问后端当前是否在冷却——状态在后端，刷新页面也拦得住。 */
  async function refreshCooldown() {
    try {
      const state = await apiGet("trial/live");
      syncCooldown(state && state.cooldown_remaining);
    } catch (err) {
      syncCooldown(0);
    }
  }


  /* 单独测私信 / 真 @。两者都会真的往 B站 发东西，后端有 30 秒共用冷却。 */
  const TEST_LABEL = { private: "测私信", mention: "测提及" };

  async function runTest(kind) {
    const btn = kind === "private" ? el.testPrivate : el.testMention;
    const label = TEST_LABEL[kind];
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
    clear(el.trialPlan);

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

    if (!res || res.error === undefined) return;

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
    el.trial.disabled = true;
    el.trial.textContent = "刷片中…";
    el.error.hidden = true;
    el.trialCard.hidden = false;
    markCard(el.trialCard, "idle");
    el.trialNote.textContent = "正在刷 B站：取片 → 分析 → 评价 → 按配置互动。可能要一两分钟…";
    try {
      const started = await apiPost("trial/live");
      if (!started || !started.started) {
        el.trialNote.textContent = (started && started.reason) || "启动失败";
        syncCooldown((started && started.retry_after) || 0);
        return;
      }
      renderLive(await pollLive());
    } catch (err) {
      el.trialCard.hidden = false;
      markCard(el.trialCard, "bad");
      el.error.hidden = false;
      el.error.textContent = `刷片失败：${err?.message || err}`;
    } finally {
      el.trial.disabled = false;
      el.trial.textContent = "刷一个";
      await refreshCooldown();
    }
  }

  /* 轮询真跑状态。一次可能一两分钟，所以每 2 秒问一次，最多等 6 分钟。 */
  async function pollLive() {
    const deadline = Date.now() + 6 * 60 * 1000;
    let last = null;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
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
    clear(el.trialPlan);

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

  el.reload.addEventListener("click", load);
  el.trial.addEventListener("click", runTrial);
  el.testPrivate.addEventListener("click", () => runTest("private"));
  el.testMention.addEventListener("click", () => runTest("mention"));
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
      el.reload.removeEventListener("click", load);
      el.trial.removeEventListener("click", runTrial);
    },
  };
}
