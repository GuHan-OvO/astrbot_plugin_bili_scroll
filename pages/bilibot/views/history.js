// 「看过的视频」内嵌视图：从 pages/history/ 的独立页面迁移而来。
//
// 原来这一页是 AstrBot 宿主用 iframe 加载的独立 HTML（index.html + app.js + style.css），
// 现在收进控制中心 SPA 的 #content 里当内页，由本模块自渲染。
//
// 为什么用 Shadow DOM：原页面的 style.css 是照整页写的（:root 里定义令牌、html/body 铺底、
// .page / .body / .card / .title 这类通用类名），直接塞进控制中心会和外壳的样式互相污染。
// Shadow DOM 把样式作用域钉在 host 内部：两边的同名选择器、同名类名互不可见。
//
// 样式只做一类适配：:root / html / body 这些「全局根」选择器在 shadow 内不生效
// （:root 指向文档根，不是 shadow root），统一改写成 :host，让令牌、底色与字体
// 挂在 host 元素上、再正常继承给 shadow 内的内容。其余选择器、类名、变量名一律原样。
//
// 全局副作用（document 上的 keydown、<html> 的 overflow 锁、定时器）都在 destroy() 里撤销。

const HISTORY_HTML = `
  <div class="ambient" aria-hidden="true"><span></span><span></span></div>

  <div class="page">
    <header class="page-bar">
      <div class="bar-copy">
        <span class="eyebrow">BILIBOT / HISTORY</span>
        <h1>看过的视频</h1>
        <p class="bar-sub" id="stats" aria-live="polite"></p>
      </div>
      <div class="bar-actions">
        <button id="reset" class="btn soft" type="button">重置筛选</button>
      </div>
    </header>

    <section class="filters" aria-label="筛选条件">
      <label class="field">
        <span>分数</span>
        <div class="range-pair">
          <input id="min-score" type="number" min="0" max="10" step="0.5" placeholder="最低" aria-label="最低分" />
          <i>–</i>
          <input id="max-score" type="number" min="0" max="10" step="0.5" placeholder="最高" aria-label="最高分" />
        </div>
      </label>
      <label class="field">
        <span>心情</span>
        <select id="mood" aria-label="按心情筛选">
          <option value="">全部</option>
          <option>开心</option><option>平静</option><option>无聊</option>
          <option>感动</option><option>好笑</option><option>震撼</option>
          <option>困惑</option><option>未知</option>
        </select>
      </label>
      <label class="field">
        <span>来源</span>
        <select id="source" aria-label="按来源筛选">
          <option value="">全部</option>
          <option value="search">搜索</option>
          <option value="follow">关注</option>
          <option value="pool">视频池</option>
        </select>
      </label>
      <label class="field">
        <span>状态</span>
        <select id="state" aria-label="按状态筛选">
          <option value="">全部</option>
          <option value="recommended">推荐过</option>
          <option value="not-recommended">没推荐</option>
          <option value="failed">评价失败</option>
        </select>
      </label>
      <label class="field grow">
        <span>搜索</span>
        <input id="q" type="search" placeholder="标题 / UP / 理由" aria-label="搜索标题、UP 或理由" />
      </label>
    </section>

    <div class="result-bar" aria-live="polite">
      <span id="count" class="count"></span>
    </div>

    <main id="grid" class="grid" aria-live="polite"></main>
    <p id="empty" class="empty" hidden>还没有看过的记录。等它跑完一轮就会出现。</p>
    <div id="error" class="error" hidden role="alert">
      <strong>加载失败</strong>
      <p id="error-detail"></p>
      <button id="error-retry" class="btn soft" type="button">重新加载</button>
    </div>

    <nav id="pager" class="pager" aria-label="分页">
      <button id="prev" type="button" class="btn soft" aria-label="上一页">上一页</button>
      <span id="page-info" class="page-info"></span>
      <button id="next" type="button" class="btn soft" aria-label="下一页">下一页</button>
    </nav>
  </div>

  <div id="drawer-backdrop" class="drawer-backdrop" hidden></div>
  <aside id="drawer" class="drawer" hidden aria-label="视频详情" role="dialog" aria-modal="true"></aside>
`;

// style.css 全文内联。不用 <link>：宿主会重写资源 URL，动态插入的 link 拿不到 asset_token 会 403。
// 转义检查：原 CSS 里没有反引号、没有 ${、没有反斜杠，可直接放进模板字符串。
// 仅改选择器：:root / html / body → :host；深色分支改成 :host([data-theme="dark"])（见下方注释）。
// 其余（含 .body 这个类名）保持原样。
const HISTORY_CSS = `
/* 「看过的视频」页面。
 *
 * 视觉令牌不在 shadow 内重抄一份：CSS 自定义属性本来就会从宿主继承，
 * 重抄会让控制中心换主题（accent、对比度、阴影、圆角）时这一页纹丝不动。
 * 这里只补宿主没有的别名；:root 上的其余令牌由宿主继承下来。
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
  /* 底色挂在根元素上，.ambient 才能用 z-index:-1 画在正文之下 */
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
p {
  margin: 0;
}

img {
  display: block;
  max-width: 100%;
}

button,
input,
select {
  font: inherit;
  color: inherit;
}

button {
  border: 0;
  background: none;
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
  opacity: 0.75;
}

.ambient span:first-child {
  top: -12vh;
  left: -8vw;
  width: 46vw;
  height: 46vw;
  background: var(--ambient);
  animation: drift 28s var(--ease-out) infinite alternate;
}

.ambient span:last-child {
  right: -10vw;
  bottom: -20vh;
  width: 38vw;
  height: 38vw;
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

.bar-sub b {
  color: var(--text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.bar-sub span + span::before {
  content: "·";
  margin: 0 8px;
  color: var(--text-3);
}

.bar-actions {
  display: flex;
  gap: 8px;
  flex: none;
}

/* ── 按钮 ───────────────────────────────────────────────────────────── */

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
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
  background: color-mix(in srgb, var(--text) 8%, var(--surface-sunken));
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

/* ── 筛选 ───────────────────────────────────────────────────────────── */

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: flex-end;
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow-1);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.field > span {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
}

.field.grow {
  flex: 1 1 200px;
}

.range-pair {
  display: flex;
  align-items: center;
  gap: 6px;
}

.range-pair i {
  color: var(--text-3);
  font-style: normal;
}

input[type="number"],
input[type="search"],
select {
  height: 36px;
  padding: 0 11px;
  border: 1px solid var(--line-input);
  border-radius: var(--r-sm);
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  transition: border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

input[type="number"] {
  width: 74px;
  font-variant-numeric: tabular-nums;
}

input[type="search"] {
  width: 100%;
}

select {
  padding-right: 28px;
  appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: calc(100% - 15px) calc(50% + 1px), calc(100% - 10px) calc(50% + 1px);
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
  cursor: pointer;
}

input:hover,
select:hover {
  border-color: color-mix(in srgb, var(--text) 26%, transparent);
}

input:focus,
select:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

::placeholder {
  color: var(--text-3);
  opacity: 1;
}

/* ── 结果条 ─────────────────────────────────────────────────────────── */

.result-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 24px;
  margin-bottom: 12px;
}

.count {
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ── 卡片网格 ───────────────────────────────────────────────────────── */

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(244px, 1fr));
  gap: 16px;
}

.card {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  box-shadow: var(--shadow-1);
  cursor: pointer;
  animation: cardIn var(--dur-slow) var(--ease-out) both;
  transition: transform var(--dur-base) var(--ease-apple),
    box-shadow var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out);
}

@keyframes cardIn {
  from {
    opacity: 0;
    transform: translate3d(0, 10px, 0);
  }
}

.card:nth-child(1) { animation-delay: 0ms; }
.card:nth-child(2) { animation-delay: 26ms; }
.card:nth-child(3) { animation-delay: 52ms; }
.card:nth-child(4) { animation-delay: 78ms; }
.card:nth-child(5) { animation-delay: 104ms; }
.card:nth-child(6) { animation-delay: 130ms; }
.card:nth-child(7) { animation-delay: 156ms; }
.card:nth-child(n + 8) { animation-delay: 180ms; }

.card:hover {
  transform: translateY(-3px);
  border-color: var(--line-strong);
  box-shadow: var(--shadow-2);
}

.card:active {
  transform: translateY(-1px) scale(0.995);
}

.thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  background: linear-gradient(135deg, var(--surface-sunken), var(--surface-muted));
  overflow: hidden;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform var(--dur-slow) var(--ease-apple);
}

.card:hover .thumb img {
  transform: scale(1.035);
}

.score {
  position: absolute;
  top: 8px;
  right: 8px;
  min-width: 36px;
  padding: 2px 7px;
  border-radius: var(--r-pill);
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  text-align: center;
  backdrop-filter: blur(6px);
}

.score.good {
  background: color-mix(in srgb, var(--green) 88%, transparent);
}

.score.mid {
  background: color-mix(in srgb, var(--orange) 88%, transparent);
}

.score.low {
  background: rgba(90, 90, 96, 0.8);
}

.score.failed {
  background: color-mix(in srgb, var(--red) 88%, transparent);
}

.body {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px 14px 14px;
}

.title {
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--text-strong);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.why {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 2px;
}

.tag {
  padding: 1px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-pill);
  font-size: 10.5px;
  color: var(--text-3);
}

.tag.on {
  border-color: var(--accent-ring);
  background: var(--accent-soft);
  color: var(--accent);
}

.tag.fail {
  border-color: color-mix(in srgb, var(--red) 34%, transparent);
  background: var(--red-soft);
  color: var(--red);
}

/* 骨架屏：只出现在首次加载，避免空白闪烁 */
.skeleton {
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  overflow: hidden;
}

.skeleton .thumb {
  background: linear-gradient(90deg, var(--surface-sunken) 25%, var(--surface-muted) 37%, var(--surface-sunken) 63%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}

.skeleton .body {
  gap: 8px;
}

.skeleton i {
  display: block;
  height: 10px;
  border-radius: var(--r-pill);
  background: linear-gradient(90deg, var(--surface-sunken) 25%, var(--surface-muted) 37%, var(--surface-sunken) 63%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}

.skeleton i:nth-child(2) {
  width: 62%;
}

@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}

/* ── 空态 / 错误 ────────────────────────────────────────────────────── */

/* 视图内自带完整样式表，但没有宿主 base.css 的 [hidden] 兜底；
   .drawer 的 display:flex 会盖掉浏览器默认的 [hidden]，所以这里必须显式声明。 */
[hidden] {
  display: none !important;
}

.empty,
.error {
  padding: 64px 16px;
  text-align: center;
  color: var(--text-3);
}

/* 错误态做成一张可重试的卡片，而不是一条和页面语言不搭的红色横幅 */
.error {
  display: grid;
  justify-items: start;
  gap: 6px;
  max-width: 560px;
  margin: 8px auto 0;
  padding: 20px;
  border: 1px solid color-mix(in srgb, var(--red) 26%, var(--line));
  border-radius: var(--r-md);
  background: var(--surface);
  color: var(--text);
  text-align: left;
  box-shadow: var(--shadow-1);
}

.error > strong {
  font-size: 14px;
  font-weight: 600;
  color: var(--red);
}

.error > p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-2);
  overflow-wrap: anywhere;
}

.error .btn {
  margin-top: 6px;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 24px;
}

.page-info {
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ── 详情抽屉 ───────────────────────────────────────────────────────── */

.drawer-backdrop {
  position: fixed;
  inset: 0;
  /* 必须高于宿主顶栏(30)、侧栏(40)与保存条(50)，否则抽屉头部的关闭按钮会被顶栏盖住。 */
  z-index: 60;
  background: var(--backdrop);
  backdrop-filter: blur(6px);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out);
}

.drawer-backdrop.is-visible {
  opacity: 1;
}

.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 61;
  display: flex;
  flex-direction: column;
  width: min(540px, 94vw);
  overflow-y: auto;
  padding: 22px 24px 40px;
  border-left: 1px solid var(--line);
  background: var(--surface);
  box-shadow: var(--shadow-3);
  transform: translate3d(100%, 0, 0);
  transition: transform var(--dur-slow) var(--ease-apple);
}

.drawer.is-visible {
  transform: none;
}

.drawer-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  position: sticky;
  top: -22px;
  padding: 10px 0 12px;
  margin: -22px 0 0;
  background: var(--surface);
}

.drawer-head h2 {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: 17px;
  line-height: 1.35;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-strong);
}

.drawer-close {
  display: grid;
  place-items: center;
  flex: none;
  width: 36px;
  height: 36px;
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  color: var(--text-2);
  font-size: 17px;
  line-height: 1;
  transition: color var(--dur-fast) var(--ease-out), background-color var(--dur-fast) var(--ease-out);
}

.drawer-close:hover {
  color: var(--text);
  background: color-mix(in srgb, var(--text) 10%, var(--surface-sunken));
}

.drawer dl {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 7px 12px;
  margin: 4px 0 18px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-muted);
}

.drawer dt {
  font-size: 12px;
  color: var(--text-3);
}

.drawer dd {
  margin: 0;
  font-size: 13px;
  color: var(--text);
  word-break: break-word;
}

.detail-section {
  margin-top: 18px;
  animation: cardIn var(--dur-base) var(--ease-out) both;
}

.detail-section h3 {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
}

.detail-section .quote {
  padding: 10px 12px;
  border-radius: var(--r-sm);
  background: var(--surface-muted);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  color: var(--text-2);
}

.drawer-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 22px;
  padding: 8px 16px;
  border-radius: var(--r-pill);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: background-color var(--dur-fast) var(--ease-out);
}

.drawer-link:hover {
  background: color-mix(in srgb, var(--accent) 18%, transparent);
}

/* ── 响应式与无障碍 ─────────────────────────────────────────────────── */

@media (max-width: 640px) {
  .grid {
    grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
    gap: 12px;
  }

  .body {
    padding: 10px 11px 12px;
  }

  .title {
    font-size: 12.5px;
  }

  .filters {
    gap: 10px 12px;
    padding: 12px;
  }

  .drawer {
    width: 100%;
    border-left: 0;
  }

  /* 触屏下把可点目标抬到 44px */
  .btn,
  input[type="number"],
  input[type="search"],
  select {
    height: 44px;
  }

  .drawer-close {
    width: 44px;
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

// 挂载到控制中心 SPA 给的容器上：容器由外壳创建（.embedded-page），shadow 内的 DOM
// 是本页面唯一会碰的节点；切页时外壳调 destroy()，全局监听与锁都从这里撤销。
export function mountHistory(host) {
  // 桥在挂载时读取：视图可能在 bridge 注入之后才挂上来，模块顶层读会拿到过期的 null。
  const bridge = window.AstrBotPluginPage || null;

  const PAGE_SIZE = 24;

  const shadow = host.shadowRoot || host.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>${HISTORY_CSS}</style>${HISTORY_HTML}`;

  const el = {
    grid: shadow.querySelector("#grid"),
    stats: shadow.querySelector("#stats"),
    count: shadow.querySelector("#count"),
    empty: shadow.querySelector("#empty"),
    error: shadow.querySelector("#error"),
    errorDetail: shadow.querySelector("#error-detail"),
    errorRetry: shadow.querySelector("#error-retry"),
    pager: shadow.querySelector("#pager"),
    pageInfo: shadow.querySelector("#page-info"),
    prev: shadow.querySelector("#prev"),
    next: shadow.querySelector("#next"),
    reset: shadow.querySelector("#reset"),
    drawer: shadow.querySelector("#drawer"),
    backdrop: shadow.querySelector("#drawer-backdrop"),
    minScore: shadow.querySelector("#min-score"),
    maxScore: shadow.querySelector("#max-score"),
    mood: shadow.querySelector("#mood"),
    source: shadow.querySelector("#source"),
    state: shadow.querySelector("#state"),
    q: shadow.querySelector("#q"),
  };

  const state = {
    offset: 0,
    total: 0,
    items: [],
    loading: false,
    firstLoad: true,
    returnFocus: null,
    error: "",
    // 请求序号：筛选/翻页/搜索可能并发，只让最新一次写 UI。
    seq: 0,
    detailSeq: 0,
    destroyed: false,
    closeTimer: 0,
  };

  function unwrap(result) {
    if (result && result.status === "ok" && Object.prototype.hasOwnProperty.call(result, "data")) {
      return result.data;
    }
    if (result && result.status === "error") throw new Error(result.message || "请求失败");
    return result?.data ?? result ?? {};
  }

  async function apiGet(path, query = {}) {
    if (!bridge) throw new Error("这个页面需要在 AstrBot 里打开（缺少插件页面桥）");
    const params = {};
    for (const [k, v] of Object.entries(query)) {
      if (v !== "" && v !== null && v !== undefined) params[k] = v;
    }
    return unwrap(await bridge.apiGet(path, params));
  }

  function buildQuery() {
    const q = { offset: state.offset, limit: PAGE_SIZE };
    const min = el.minScore.value.trim();
    const max = el.maxScore.value.trim();
    if (min) q.min_score = min;
    if (max) q.max_score = max;
    if (el.mood.value) q.mood = el.mood.value;
    if (el.source.value) q.source = el.source.value;
    if (el.q.value.trim()) q.q = el.q.value.trim();

    const picked = el.state.value;
    if (picked === "recommended") q.recommended = 1;
    if (picked === "not-recommended") q.recommended = 0;
    if (picked === "failed") q.failed = 1;
    return q;
  }

  function scoreClass(score, failed) {
    if (failed) return "failed";
    if (score >= 8) return "good";
    if (score >= 5) return "mid";
    return "low";
  }

  function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function renderStats(stats) {
    el.stats.replaceChildren();
    // 读取失败时传 null：清空统计行，而不是把 "共 0 · 平均分 0" 当成真实数据。
    if (!stats) return;
    const parts = [
      ["共", stats.total ?? 0],
      ["平均分", stats.average_score ?? 0],
      ["今日", stats.today ?? 0],
      ["推荐过", stats.recommended ?? 0],
    ];
    if (stats.failed) parts.push(["失败", stats.failed]);
    for (const [label, value] of parts) {
      const span = node("span");
      span.append(document.createTextNode(`${label} `), node("b", null, value));
      el.stats.appendChild(span);
    }
  }

  function renderSkeleton(count = 6) {
    const cards = [];
    for (let i = 0; i < count; i += 1) {
      const card = node("div", "skeleton");
      const thumb = node("div", "thumb");
      const body = node("div", "body");
      body.append(node("i"), node("i"));
      card.append(thumb, body);
      cards.push(card);
    }
    el.grid.replaceChildren(...cards);
  }

  function renderCard(item) {
    const card = node("button", "card");
    card.type = "button";
    card.setAttribute("aria-label", `${item.title || item.bvid || "视频"}，打开详情`);

    const thumb = node("div", "thumb");
    if (item.pic) {
      const img = node("img");
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.alt = "";
      img.src = item.pic.startsWith("//") ? `https:${item.pic}` : item.pic;
      img.addEventListener("error", () => img.remove(), { once: true });
      thumb.appendChild(img);
    }
    const score = node(
      "span",
      `score ${scoreClass(Number(item.score) || 0, item.failed)}`,
      item.failed ? "失败" : Number(item.score || 0).toFixed(1)
    );
    thumb.appendChild(score);
    card.appendChild(thumb);

    const body = node("div", "body");
    body.appendChild(node("div", "title", item.title || item.bvid || "（无标题）"));
    body.appendChild(
      node("div", "meta", [item.up_name, item.time, item.tname].filter(Boolean).join(" · "))
    );
    const why = item.score_reason || item.review || item.content_summary || "";
    if (why) body.appendChild(node("div", "why", why));

    const tags = node("div", "tags");
    if (item.recommended) tags.appendChild(node("span", "tag on", "推荐过"));
    if (item.failed) tags.appendChild(node("span", "tag fail", "评价失败"));
    if (item.mood) tags.appendChild(node("span", "tag", item.mood));
    if (tags.childElementCount) body.appendChild(tags);

    card.appendChild(body);
    card.addEventListener("click", () => openDetail(item.bvid));
    return card;
  }

  function hasFilters() {
    return Boolean(
      el.minScore.value.trim() ||
      el.maxScore.value.trim() ||
      el.mood.value ||
      el.source.value ||
      el.state.value ||
      el.q.value.trim()
    );
  }

  function render() {
    el.grid.replaceChildren(...state.items.map(renderCard));
    const failed = Boolean(state.error);
    el.error.hidden = !failed;
    if (failed) el.errorDetail.textContent = state.error;
    // 错误态与空态互斥：失败时绝不再叠加「还没有看过的记录」。
    const noData = !state.loading && !failed && state.total === 0 && state.items.length === 0;
    el.empty.hidden = !noData;
    el.empty.textContent = noData && hasFilters()
      ? "没有符合这些筛选条件的记录。"
      : "还没有看过的记录。等它跑完一轮就会出现。";
    // 失败时页码没有意义（offset 已归 0），整条分页隐藏。
    el.pager.hidden = failed;
    const page = Math.floor(state.offset / PAGE_SIZE) + 1;
    const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    el.pageInfo.textContent = `第 ${page} / ${pages} 页 · 共 ${state.total} 条`;
    el.prev.disabled = state.loading || state.offset <= 0;
    el.next.disabled = state.loading || state.offset + PAGE_SIZE >= state.total;
    el.count.textContent = state.total
      ? `第 ${state.offset + 1}–${Math.min(state.offset + PAGE_SIZE, state.total)} 条，共 ${state.total} 条`
      : "";
  }

  async function load() {
    const seq = ++state.seq;
    state.loading = true;
    state.error = "";
    el.error.hidden = true;
    el.pager.hidden = false;
    // 请求期间禁掉翻页，避免连点下一页把 offset 推成越界页（「第 6 / 5 页」）。
    el.prev.disabled = true;
    el.next.disabled = true;
    if (state.firstLoad) renderSkeleton();
    try {
      const data = await apiGet("history", buildQuery());
      if (seq !== state.seq || state.destroyed) return;
      state.items = Array.isArray(data.items) ? data.items : [];
      state.total = Number(data.total ?? state.items.length);
      renderStats(data.stats || {});
    } catch (err) {
      if (seq !== state.seq || state.destroyed) return;
      state.items = [];
      state.total = 0;
      state.offset = 0;
      state.error = err?.message || String(err);
      renderStats(null);
    } finally {
      if (seq !== state.seq || state.destroyed) return;
      state.loading = false;
      state.firstLoad = false;
      render();
    }
  }

  let closeTimer = 0;
  let openFrame = 0;
  // 打开抽屉前 html 的 overflow 值：关闭时只恢复自己改过的那次，
  // 不要无条件清空（宿主可能同时锁着页面）。
  let previousOverflow = null;

  function openDrawerShell() {
    window.clearTimeout(closeTimer);
    // 320ms 关闭动画期间重新打开：清掉待执行的关闭定时器，否则新抽屉会被旧定时器清空。
    el.drawer.hidden = false;
    el.backdrop.hidden = false;
    // 原实现是 document.activeElement；焦点在 shadow 内时它只会返回 host，
    // 用 shadow.activeElement 才能取到真正触发抽屉的那张卡片。
    state.returnFocus = shadow.activeElement;
    openFrame = requestAnimationFrame(() => {
      el.backdrop.classList.add("is-visible");
      el.drawer.classList.add("is-visible");
      el.drawer.querySelector(".drawer-close")?.focus({ preventScroll: true });
    });
    if (previousOverflow === null) {
      previousOverflow = document.documentElement.style.overflow;
      document.documentElement.style.overflow = "hidden";
    }
  }

  function closeDrawer(options = {}) {
    if (el.drawer.hidden) return;
    el.backdrop.classList.remove("is-visible");
    el.drawer.classList.remove("is-visible");
    window.clearTimeout(closeTimer);
    closeTimer = window.setTimeout(() => {
      el.drawer.hidden = true;
      el.backdrop.hidden = true;
      el.drawer.replaceChildren();
    }, 320);
    if (previousOverflow !== null) {
      document.documentElement.style.overflow = previousOverflow;
      previousOverflow = null;
    }
    if (options.restoreFocus !== false && state.returnFocus instanceof HTMLElement && state.returnFocus.isConnected) {
      state.returnFocus.focus({ preventScroll: true });
    }
  }

  async function openDetail(bvid) {
    if (!bvid) return;
    const seq = ++state.detailSeq;
    openDrawerShell();
    // 读取中也保留头部关闭按钮：否则加载失败时只剩 Esc 能退出。
    const head = node("div", "drawer-head");
    const close = node("button", "drawer-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "关闭详情");
    close.addEventListener("click", () => closeDrawer());
    head.append(node("h2", null, "视频详情"), close);
    el.drawer.replaceChildren(head, node("p", "meta", "读取中…"));
    try {
      const item = await apiGet("history/detail", { bvid });
      if (seq !== state.detailSeq || state.destroyed) return;
      renderDetail(item);
    } catch (err) {
      if (seq !== state.detailSeq || state.destroyed) return;
      el.drawer.replaceChildren(head, node("p", "error", `读取失败：${err?.message || err}`));
    }
    el.drawer.scrollTop = 0;
  }

  function renderDetail(item) {
    const frag = document.createDocumentFragment();

    const head = node("div", "drawer-head");
    const close = node("button", "drawer-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "关闭详情");
    close.addEventListener("click", closeDrawer);
    head.append(node("h2", null, item.title || item.bvid), close);
    frag.appendChild(head);

    const dl = node("dl");
    const rows = [
      ["UP", item.up_name],
      ["时间", item.time],
      ["分数", item.failed ? "评价失败" : Number(item.score || 0).toFixed(1)],
      ["分区", item.tname],
      ["来源", item.source_detail || item.source],
      ["心情", item.mood],
      ["看过", item.seen_times ? `${item.seen_times} 次` : ""],
      ["推荐过", item.recommended ? item.recommended_at || "是" : "否"],
    ];
    let rowCount = 0;
    for (const [label, value] of rows) {
      if (!value) continue;
      dl.append(node("dt", null, label), node("dd", null, value));
      rowCount += 1;
    }
    if (rowCount) frag.appendChild(dl);

    const sections = [
      ["为什么值得", item.score_reason],
      ["它的感想", item.review],
      ["评论区说的", item.comment],
      ["推荐给主人的理由", item.recommend_reason],
      ["内容概要", item.content_summary],
      ["动作", Array.isArray(item.actions) ? item.actions.join(" / ") : item.actions],
      ["分析依据", item.analysis_basis],
    ];
    for (const [title, value] of sections) {
      if (!value) continue;
      const section = node("section", "detail-section");
      section.append(node("h3", null, title), node("div", "quote", value));
      frag.appendChild(section);
    }

    if (item.bvid) {
      const link = node("a", "drawer-link", "在 B站 打开");
      link.href = `https://www.bilibili.com/video/${encodeURIComponent(item.bvid)}`;
      link.target = "_blank";
      link.rel = "noreferrer";
      frag.appendChild(link);
    }

    el.drawer.replaceChildren(frag);
  }

  function resetFilters() {
    el.minScore.value = "";
    el.maxScore.value = "";
    el.mood.value = "";
    el.source.value = "";
    el.state.value = "";
    el.q.value = "";
    state.offset = 0;
    load();
  }

  let searchTimer = 0;
  el.q.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.offset = 0;
      state.firstLoad = false;
      load();
    }, 300);
  });

  // 数字筛选也绑 input：只在 change 上绑意味着「敲完不失焦就看不到结果」。
  let scoreTimer = 0;
  for (const control of [el.minScore, el.maxScore]) {
    control.addEventListener("input", () => {
      clearTimeout(scoreTimer);
      scoreTimer = setTimeout(() => {
        state.offset = 0;
        state.firstLoad = false;
        load();
      }, 300);
    });
  }

  for (const control of [el.mood, el.source, el.state]) {
    control.addEventListener("change", () => {
      state.offset = 0;
      state.firstLoad = false;
      load();
    });
  }

  el.errorRetry.addEventListener("click", () => load());

  el.prev.addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    state.firstLoad = false;
    load();
  });

  el.next.addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    state.firstLoad = false;
    load();
  });

  el.reset.addEventListener("click", resetFilters);
  el.backdrop.addEventListener("click", closeDrawer);

  // Escape 关抽屉，Tab 循环约束在抽屉内（aria-modal 不能只写在属性上）。
  // 监听留在 document 上（而不是 shadow）：抽屉打开时焦点可能在 shadow 外，
  // 只有 document 上的监听能稳定收到 keydown；destroy() 里摘掉。
  const DRAWER_FOCUSABLE = 'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

  function onKeydown(event) {
    if (event.key === "Escape") {
      closeDrawer();
      return;
    }
    if (event.key !== "Tab" || el.drawer.hidden) return;
    const items = [...el.drawer.querySelectorAll(DRAWER_FOCUSABLE)]
      .filter((node) => node.offsetWidth || node.offsetHeight || node.getClientRects().length);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = shadow.activeElement;
    if (event.shiftKey && (active === first || !el.drawer.contains(active))) {
      event.preventDefault();
      last.focus({ preventScroll: true });
    } else if (!event.shiftKey && (active === last || !el.drawer.contains(active))) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  }

  document.addEventListener("keydown", onKeydown);

  // 深浅色由 CSS 令牌 + :host([data-theme]) 处理（控制中心手动切换时同步到宿主节点），
  // JS 不需要参与；原页面同步 <meta name="theme-color"> 的逻辑属于外壳职责，这里没有。
  // （原页面的 matchMedia 只同步 <meta name="theme-color">，那是宿主页面的节点，
  //  属于控制中心外壳的职责，这里不碰；本模块只操作 shadow 内的 DOM。）

  function destroy() {
    state.destroyed = true;
    // 递增序号让在途请求的回包失效，不再写已经脱离文档的 shadow。
    state.seq += 1;
    state.detailSeq += 1;
    closeDrawer({ restoreFocus: false });
    document.removeEventListener("keydown", onKeydown);
    if (previousOverflow !== null) {
      document.documentElement.style.overflow = previousOverflow;
      previousOverflow = null;
    }
    clearTimeout(searchTimer);
    clearTimeout(scoreTimer);
    clearTimeout(closeTimer);
    cancelAnimationFrame(openFrame);
  }

  if (bridge?.ready) {
    Promise.resolve(bridge.ready()).then(load).catch(() => load());
  } else {
    load();
  }

  return { destroy };
}
