// 「看过的视频」页面。数据来自插件自己的 WebUI 路由：
//   GET  history          → { status:"ok", data:{ total, offset, limit, stats, items } }
//   GET  history/detail   → { status:"ok", data: entry }
//
// 所有 B站 来的文本（标题、UP、评论）都只用 textContent 写入，不拼 HTML。

const bridge = window.AstrBotPluginPage || null;

const PAGE_SIZE = 24;

const el = {
  grid: document.getElementById("grid"),
  stats: document.getElementById("stats"),
  empty: document.getElementById("empty"),
  error: document.getElementById("error"),
  pageInfo: document.getElementById("page-info"),
  prev: document.getElementById("prev"),
  next: document.getElementById("next"),
  reset: document.getElementById("reset"),
  drawer: document.getElementById("drawer"),
  minScore: document.getElementById("min-score"),
  maxScore: document.getElementById("max-score"),
  mood: document.getElementById("mood"),
  source: document.getElementById("source"),
  state: document.getElementById("state"),
  q: document.getElementById("q"),
};

const state = { offset: 0, total: 0, items: [], loading: false };

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

function renderStats(stats = {}) {
  el.stats.replaceChildren();
  const parts = [
    ["共", stats.total ?? 0],
    ["平均分", stats.average_score ?? 0],
    ["今日", stats.today ?? 0],
    ["推荐过", stats.recommended ?? 0],
  ];
  if (stats.failed) parts.push(["失败", stats.failed]);
  for (const [label, value] of parts) {
    const span = node("span", null, `${label} `);
    span.appendChild(node("b", null, value));
    el.stats.appendChild(span);
    el.stats.appendChild(document.createTextNode("　"));
  }
}

function renderCard(item) {
  const card = node("button", "card");
  card.type = "button";

  const thumb = node("div", "thumb");
  if (item.pic) {
    const img = node("img");
    img.loading = "lazy";
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

function render() {
  el.grid.replaceChildren(...state.items.map(renderCard));
  el.empty.hidden = state.total !== 0 || state.loading;
  const page = Math.floor(state.offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
  el.pageInfo.textContent = `第 ${page} / ${pages} 页 · 共 ${state.total} 条`;
  el.prev.disabled = state.offset <= 0;
  el.next.disabled = state.offset + PAGE_SIZE >= state.total;
}

async function load() {
  state.loading = true;
  el.error.hidden = true;
  try {
    const data = await apiGet("history", buildQuery());
    state.items = Array.isArray(data.items) ? data.items : [];
    state.total = Number(data.total || 0);
    renderStats(data.stats || {});
  } catch (err) {
    state.items = [];
    state.total = 0;
    el.error.hidden = false;
    el.error.textContent = `加载失败：${err?.message || err}`;
  } finally {
    state.loading = false;
    render();
  }
}

function closeDrawer() {
  el.drawer.hidden = true;
  el.drawer.replaceChildren();
}

async function openDetail(bvid) {
  if (!bvid) return;
  el.drawer.hidden = false;
  el.drawer.replaceChildren(node("p", "meta", "读取中…"));
  try {
    const item = await apiGet("history/detail", { bvid });
    renderDetail(item);
  } catch (err) {
    el.drawer.replaceChildren(node("p", "error", `读取失败：${err?.message || err}`));
  }
}

function renderDetail(item) {
  const frag = document.createDocumentFragment();

  const close = node("button", "close", "×");
  close.type = "button";
  close.addEventListener("click", closeDrawer);
  frag.appendChild(close);

  frag.appendChild(node("h2", null, item.title || item.bvid));

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
  for (const [label, value] of rows) {
    if (!value) continue;
    dl.appendChild(node("dt", null, label));
    dl.appendChild(node("dd", null, value));
  }
  frag.appendChild(dl);

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
    const section = node("section");
    section.appendChild(node("h3", null, title));
    section.appendChild(node("div", "quote", value));
    frag.appendChild(section);
  }

  if (item.bvid) {
    const link = node("a", null, "在 B站 打开");
    link.href = `https://www.bilibili.com/video/${encodeURIComponent(item.bvid)}`;
    link.target = "_blank";
    link.rel = "noreferrer";
    const section = node("section");
    section.appendChild(link);
    frag.appendChild(section);
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
    load();
  }, 300);
});

for (const control of [el.minScore, el.maxScore, el.mood, el.source, el.state]) {
  control.addEventListener("change", () => {
    state.offset = 0;
    load();
  });
}

el.prev.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - PAGE_SIZE);
  load();
});

el.next.addEventListener("click", () => {
  state.offset += PAGE_SIZE;
  load();
});

el.reset.addEventListener("click", resetFilters);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

if (bridge?.ready) {
  Promise.resolve(bridge.ready()).then(load).catch(() => load());
} else {
  load();
}
