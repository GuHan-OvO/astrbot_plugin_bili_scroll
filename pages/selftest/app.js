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
  return unwrap(await bridge.apiGet(path, query));
}

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function clear(node) {
  node.replaceChildren();
}

function addRow(dl, label, value, tone) {
  dl.appendChild(node("dt", null, label));
  const dd = node("dd", tone ? tone : null, value === undefined || value === null || value === "" ? "—" : value);
  dl.appendChild(dd);
  return dd;
}

function renderModule(info) {
  clear(el.moduleList);
  if (!info) return addRow(el.moduleList, "状态", "读取失败", "bad-text");
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
    return;
  }
  el.configTotal.textContent = `配置项共 ${cfg.total_keys} 个`;
  for (const item of cfg.required || []) {
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
  if (!data) return addRow(el.dataList, "状态", "读取失败", "bad-text");

  const watch = data.watch_log || {};
  addRow(el.dataList, "看过的视频", watch.count === null ? "文件损坏" : `${watch.count} 条`);
  const verify = data.verify_log || {};
  addRow(el.dataList, "复核记录", verify.count === null ? "文件损坏" : `${verify.count} 条`);
  const db = data.database || {};
  addRow(el.dataList, "数据库", db.exists ? `存在（${Math.round((db.size || 0) / 1024)} KB）` : "尚未创建");
  addRow(el.dataList, "页面目录", `${(pages || []).length} 个`);
}

function renderRoutes(routes, pages) {
  clear(el.routeList);
  if (!routes) return addRow(el.routeList, "状态", "读取失败", "bad-text");
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

async function load() {
  el.reload.disabled = true;
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
    el.stamp.textContent = `检查于 ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    el.error.hidden = false;
    el.error.textContent = `读取失败：${err?.message || err}`;
  } finally {
    el.reload.disabled = false;
  }
}

el.reload.addEventListener("click", load);

if (bridge?.ready) {
  Promise.resolve(bridge.ready()).then(load).catch(() => load());
} else {
  load();
}
