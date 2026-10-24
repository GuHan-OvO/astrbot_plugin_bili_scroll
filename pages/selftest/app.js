// 自检页面。数据来自 GET selftest，返回结构见 core/selftest.py::collect。
// 所有文本用 textContent 写入，不拼 HTML。

const bridge = window.AstrBotPluginPage || null;

const el = {
  root: document.getElementById("root"),
  error: document.getElementById("error"),
  reload: document.getElementById("reload"),
  stamp: document.getElementById("stamp"),
  moduleList: document.getElementById("module-list"),
  configTotal: document.getElementById("config-total"),
  configRequired: document.getElementById("config-required"),
  configOptional: document.getElementById("config-optional"),
  dataList: document.getElementById("data-list"),
  routeList: document.getElementById("route-list"),
  pageList: document.getElementById("page-list"),
  trial: document.getElementById("trial"),
  trialCard: document.getElementById("card-trial"),
  trialNote: document.getElementById("trial-note"),
  trialCookie: document.getElementById("trial-cookie"),
  trialCandidates: document.getElementById("trial-candidates"),
  trialPlan: document.getElementById("trial-plan"),
};

const cards = {
  module: document.getElementById("card-module"),
  config: document.getElementById("card-config"),
  data: document.getElementById("card-data"),
  pages: document.getElementById("card-pages"),
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

async function runTrial() {
  el.trial.disabled = true;
  el.trial.textContent = "取片中…";
  el.error.hidden = true;
  el.trialCard.hidden = false;
  markCard(el.trialCard, "idle");
  el.trialNote.textContent = "正在取片…（不会互动）";
  try {
    renderTrial(await apiPost("trial"));
  } catch (err) {
    el.trialCard.hidden = true;
    el.error.hidden = false;
    el.error.textContent = `试运行失败：${err?.message || err}`;
  } finally {
    el.trial.disabled = false;
    el.trial.textContent = "试运行";
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
    renderData(data.data, data.pages);
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

window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", (event) => {
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", event.matches ? "#0b0b0d" : "#f5f5f7");
});

if (bridge?.ready) {
  Promise.resolve(bridge.ready()).then(load).catch(() => load());
} else {
  load();
}
