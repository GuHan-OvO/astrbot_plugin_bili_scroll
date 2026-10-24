// 「插件配置」页面。数据来自插件自己的 WebUI 路由：
//   GET  config/schema → { KEY: { type, description, hint, options, min, max, condition, invisible } }
//   GET  config        → { KEY: value }
//   POST config        → 提交 patch 对象，返回 { saved: [...] } 或 { status:"ok" }

const bridge = window.AstrBotPluginPage || null;

const state = {
  schema: {},
  values: {},
  draft: {},
  dirty: new Set(),
  rows: [],
  groups: [],
  query: "",
};

const el = {
  list: document.getElementById("list"),
  search: document.getElementById("search"),
  save: document.getElementById("save"),
  expand: document.getElementById("expand"),
  collapse: document.getElementById("collapse"),
  revert: document.getElementById("revert"),
  dirty: document.getElementById("dirty"),
  meta: document.getElementById("meta"),
};

const NUMERIC = new Set(["int", "float"]);

function unwrap(result) {
  if (result && typeof result === "object" && "status" in result) {
    if (result.status === "error") throw new Error(result.message || "请求失败");
    if ("data" in result) return result.data;
  }
  return result === null || result === undefined ? {} : result;
}

async function apiGet(path) {
  if (!bridge) throw new Error("该页面需要在 AstrBot 面板中打开");
  return unwrap(await bridge.apiGet(path));
}

async function apiPost(path, body) {
  if (!bridge) throw new Error("该页面需要在 AstrBot 面板中打开");
  return unwrap(await bridge.apiPost(path, body));
}

function typeOf(field) {
  return String(field.type || "string").toLowerCase();
}

function rawDesc(field) {
  return String(field.description || "");
}

function groupName(key, field) {
  const match = /^【([^】]+)】/.exec(rawDesc(field));
  let name = match ? match[1].trim() : "其它";
  if (name !== "高级") {
    const cut = name.indexOf("·");
    if (cut > 0) name = name.slice(0, cut);
  }
  return name || "其它";
}

function labelOf(key, field) {
  const text = rawDesc(field).replace(/^【[^】]*】/, "").trim();
  return text || key;
}

function currentValue(key) {
  if (Object.prototype.hasOwnProperty.call(state.draft, key)) return state.draft[key];
  return state.values[key];
}

function isVisible(key, field) {
  if (field.invisible) return false;
  const cond = field.condition;
  if (!cond || typeof cond !== "object") return true;
  for (const [dep, expected] of Object.entries(cond)) {
    if (!Object.prototype.hasOwnProperty.call(state.schema, dep)) continue;
    if (currentValue(dep) !== expected) return false;
  }
  return true;
}

function setDraft(key, value) {
  const base = state.values[key];
  const same = JSON.stringify(base) === JSON.stringify(value);
  state.draft[key] = value;
  if (same) state.dirty.delete(key);
  else state.dirty.add(key);
  refresh();
}

function buildControl(key, field) {
  const type = typeOf(field);
  const value = currentValue(key);

  if (type === "bool") {
    const wrap = document.createElement("label");
    wrap.className = "switch";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = value === true;
    input.addEventListener("change", () => setDraft(key, input.checked));
    const track = document.createElement("span");
    track.className = "track";
    wrap.append(input, track);
    return wrap;
  }

  if (field.options?.length) {
    const select = document.createElement("select");
    select.setAttribute("aria-label", labelOf(key, field));
    for (const option of field.options) {
      const node = document.createElement("option");
      node.value = String(option);
      node.textContent = String(option);
      if (String(value) === String(option)) node.selected = true;
      select.appendChild(node);
    }
    select.addEventListener("change", () => setDraft(key, select.value));
    return select;
  }

  if (NUMERIC.has(type)) {
    const input = document.createElement("input");
    input.type = "number";
    input.className = "num";
    input.step = type === "float" ? "0.01" : "1";
    if (field.min !== undefined) input.min = String(field.min);
    if (field.max !== undefined) input.max = String(field.max);
    input.value = value === null || value === undefined ? "" : String(value);
    input.addEventListener("input", () => {
      if (input.value === "" || input.value === "-") return;
      const parsed = type === "float" ? Number.parseFloat(input.value) : Number.parseInt(input.value, 10);
      if (!Number.isNaN(parsed)) setDraft(key, parsed);
    });
    return input;
  }

  if (type === "list") {
    const sample = Array.isArray(value) ? value : (Array.isArray(field.default) ? field.default : []);
    const area = document.createElement("textarea");
    area.rows = Math.min(8, Math.max(3, sample.length + 1));
    area.value = sample.map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item))).join("\n");
    area.placeholder = "每行一项";
    const numeric = sample.length > 0 && sample.every((item) => typeof item === "number");
    area.addEventListener("input", () => {
      const lines = area.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      setDraft(key, numeric ? lines.map((line) => Number(line)).filter((n) => !Number.isNaN(n)) : lines);
    });
    return area;
  }

  const text = value === null || value === undefined ? "" : String(value);
  if (type === "text" || field.editor_mode || text.includes("\n") || text.length > 90) {
    const area = document.createElement("textarea");
    area.rows = type === "text" ? 5 : 3;
    area.value = text;
    area.addEventListener("input", () => setDraft(key, area.value));
    return area;
  }

  const input = document.createElement("input");
  input.type = "text";
  input.value = text;
  input.addEventListener("input", () => setDraft(key, input.value));
  return input;
}

function buildRow(key, field) {
  const row = document.createElement("div");
  row.className = "row";
  row.dataset.key = key;

  const head = document.createElement("div");
  head.className = "row-head";

  const label = document.createElement("span");
  label.className = "label";
  label.textContent = labelOf(key, field);

  const code = document.createElement("code");
  code.className = "key";
  code.textContent = key;

  const mark = document.createElement("span");
  mark.className = "mark";
  mark.title = "未保存";

  head.append(label, code, mark);

  const control = document.createElement("div");
  control.className = "row-control";
  control.append(buildControl(key, field));

  row.append(head, control);

  if (field.hint) {
    const hint = document.createElement("p");
    hint.className = "row-hint";
    hint.textContent = String(field.hint);
    row.append(hint);
  }

  state.rows.push({ key, field, row, mark });
  return row;
}

function buildList() {
  el.list.textContent = "";
  state.rows = [];
  state.groups = [];

  const buckets = new Map();
  for (const [key, field] of Object.entries(state.schema)) {
    if (field.invisible) continue;
    const name = groupName(key, field);
    if (!buckets.has(name)) buckets.set(name, []);
    buckets.get(name).push(key);
  }

  let index = 0;
  for (const [name, keys] of buckets) {
    const section = document.createElement("details");
    section.className = "group";
    section.dataset.group = name;
    section.style.animationDelay = `${Math.min(index, 8) * 24}ms`;
    index += 1;

    const summary = document.createElement("summary");
    summary.className = "group-head";

    const gname = document.createElement("span");
    gname.className = "group-name";
    gname.textContent = name;

    const gcount = document.createElement("span");
    gcount.className = "group-count";

    summary.append(gname, gcount);
    section.append(summary);

    const body = document.createElement("div");
    body.className = "group-body";
    for (const key of keys) body.append(buildRow(key, state.schema[key]));
    section.append(body);

    el.list.append(section);
    state.groups.push({ name, section, gcount, keys });
  }

  if (!state.groups.length) {
    const empty = document.createElement("p");
    empty.className = "empty-search";
    empty.textContent = "这个插件没有可编辑的配置项。";
    el.list.append(empty);
  }

  refresh();
}

function matchesQuery(key, field) {
  if (!state.query) return true;
  const hay = `${key} ${rawDesc(field)} ${field.hint || ""}`.toLowerCase();
  return hay.includes(state.query);
}

function updateVisibility() {
  const visibleByKey = new Map();
  for (const entry of state.rows) {
    const ok = isVisible(entry.key, entry.field) && matchesQuery(entry.key, entry.field);
    visibleByKey.set(entry.key, ok);
    entry.row.hidden = !ok;
    entry.mark.classList.toggle("on", state.dirty.has(entry.key));
  }

  for (const group of state.groups) {
    let shown = 0;
    for (const key of group.keys) if (visibleByKey.get(key)) shown += 1;
    group.section.hidden = shown === 0;
    group.gcount.textContent = String(shown);
    if (state.query && shown > 0) group.section.open = true;
  }
}

function updateMeta() {
  const total = Object.keys(state.schema).length;
  const parts = [`${total} 项`, `${state.groups.length} 组`];
  if (state.query) {
    const matched = state.rows.filter((entry) => !entry.row.hidden).length;
    parts.push(`匹配 ${matched} 项`);
  }
  el.meta.textContent = parts.join(" · ");
}

function refresh() {
  updateVisibility();
  const count = state.dirty.size;
  el.save.disabled = count === 0;
  el.save.textContent = count ? `保存 (${count})` : "保存";
  el.dirty.hidden = count === 0;
  el.revert.hidden = count === 0;
  if (count) el.dirty.textContent = `${count} 处未保存`;
  updateMeta();
}

async function save() {
  if (!state.dirty.size) return;
  const patch = {};
  for (const key of state.dirty) patch[key] = state.draft[key];
  el.save.disabled = true;
  el.save.textContent = "保存中…";
  try {
    await apiPost("config", patch);
    Object.assign(state.values, patch);
    state.dirty.clear();
    state.draft = {};
    flash(`已保存 ${Object.keys(patch).length} 项`);
  } catch (error) {
    flash(error && error.message ? error.message : "保存失败", true);
  } finally {
    refresh();
  }
}

function revert() {
  state.dirty.clear();
  state.draft = {};
  buildList();
  flash("已撤销改动");
}

let flashTimer = null;
function flash(message, isError) {
  let node = document.getElementById("toast");
  if (!node) {
    node = document.createElement("div");
    node.id = "toast";
    node.className = "toast";
    document.body.append(node);
  }
  node.textContent = message;
  node.classList.toggle("error", Boolean(isError));
  node.classList.add("on");
  window.clearTimeout(flashTimer);
  flashTimer = window.setTimeout(() => node.classList.remove("on"), 2400);
}

function fail(message) {
  el.list.textContent = "";
  const box = document.createElement("div");
  box.className = "fail";
  const strong = document.createElement("strong");
  strong.textContent = "配置读取失败";
  const span = document.createElement("span");
  span.textContent = message;
  box.append(strong, span);
  el.list.append(box);
}

async function boot() {
  try {
    if (bridge && bridge.ready) await bridge.ready();
    if (!bridge) throw new Error("请从 AstrBot 面板的插件页面入口打开");
    const [schema, values] = await Promise.all([apiGet("config/schema"), apiGet("config")]);
    if (!schema || typeof schema !== "object") throw new Error("配置 schema 为空");
    state.schema = schema;
    state.values = values && typeof values === "object" ? values : {};
    buildList();
  } catch (error) {
    fail(error && error.message ? error.message : String(error));
  }
}

el.search.addEventListener("input", () => {
  state.query = el.search.value.trim().toLowerCase();
  updateVisibility();
  updateMeta();
});

el.save.addEventListener("click", save);
el.revert.addEventListener("click", revert);
el.expand.addEventListener("click", () => {
  for (const group of state.groups) if (!group.section.hidden) group.section.open = true;
});
el.collapse.addEventListener("click", () => {
  for (const group of state.groups) group.section.open = false;
});

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save();
  }
});

window.addEventListener("beforeunload", (event) => {
  if (state.dirty.size) {
    event.preventDefault();
    event.returnValue = "";
  }
});

// 顶栏随滚动收窄（motion.css 里的 .topbar.is-scrolled）
window.addEventListener("scroll", () => {
  document.querySelector(".topbar")?.classList.toggle("is-scrolled", window.scrollY > 8);
}, { passive: true });

window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", (event) => {
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", event.matches ? "#0b0b0d" : "#f5f5f7");
});

boot();
