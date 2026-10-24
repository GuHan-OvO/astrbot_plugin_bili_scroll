// 【已停用】这个脚本不再被 index.html 引用，保留仅为对照历史实现。
//
// 停用原因：AstrBot 宿主的插件页 iframe 是 `sandbox="allow-scripts allow-forms
// allow-downloads"`，**没有 allow-top-navigation**，所以这里用 <a target="_top">
// 跳宿主路由会被浏览器静默拦掉——点了没反应。宿主 bridge 也只支持 api/files/sse，
// 没有导航动作，因此「从控制中心跳到另一个插件页」在沙箱下不可行。
//
// 取代方案：把「看过的视频」「自检」做成控制中心的 SPA 内页
// （app.js 的 NAV_ITEMS + views/history.js、views/selftest.js，Shadow DOM 隔离渲染）。
//
// 下面这些历史说明仍然准确，供以后参考：
//
// 把「看过的视频」「自检」两个兄弟页面挂进 BiliBot 控制中心的侧边栏。
//
// 三个关键点：
// 1. 侧边栏是 app.js 里一大段模板字符串拼的、每次切页都会重建，所以用 MutationObserver
//    等它渲染完再补，重建一次补一次，不 hook 任何内部函数。
// 2. 图标必须直接用上游 icons.js 的 `icon()`：`.nav-item > span { flex: 1 }` 会把
//    任何 span 撑开——用 <span> 包图标会把文字挤到最右边。
// 3. 跳转**用 <a target="_top"> 而不是 JS 改 hash**：插件页面可能跑在 iframe 里，
//    脚本改 window.top.location.hash 会被 sandbox 静默拦掉（不抛错也不生效）；
//    而 target="_top" 是浏览器原生行为，由页面框架决定处理方式，不受脚本沙箱影响。
//    ↑ 这一条当时判断错了：target="_top" 同样受 sandbox 限制，见文件顶部的停用说明。
//
// 落点：优先写进侧边栏预留的 `[data-nav-slot="pages"]`（带「页面」分组标题）；
// 找不到就退回旧的插入点（`[data-page="basics"]` 之前），再找不到就追加到导航末尾。

import { icon } from "./icons.js";

const PAGES = [
  { page: "history", label: "看过的视频", icon: "video" },
  { page: "selftest", label: "自检", icon: "refresh" },
];

const OBSERVE_DEBOUNCE_MS = 120;

function pluginId() {
  const matched = location.pathname.match(/\/api\/plugin\/page\/content\/([^/]+)\//);
  return matched ? matched[1] : "astrbot_plugin_bili_scroll";
}

function targetHash(page) {
  return `#/plugin-page/${pluginId()}/${page}`;
}

function buildLink(item) {
  const link = document.createElement("a");
  link.className = "nav-item";
  link.dataset.siblingPage = item.page;
  link.href = targetHash(item.page);
  link.target = "_top";
  link.title = item.label;

  // 与上游同构：svg 直接是子元素，文字单独一个 span（span 会 flex:1）
  link.innerHTML = `${icon(item.icon, "nav-icon")}<span></span>`;
  link.querySelector("span").textContent = item.label;
  return link;
}

function container() {
  const sidebar = document.querySelector("#sidebar");
  if (!sidebar) return null;
  return sidebar.querySelector('[data-nav-slot="pages"]') || sidebar.querySelector(".nav-list");
}

function inject() {
  const host = container();
  if (!host) return;

  // 插入锚点：只有退回旧结构时才用得上
  const anchor = host.querySelector('[data-page="basics"]');

  for (const item of PAGES) {
    if (document.querySelector(`#sidebar [data-sibling-page="${item.page}"]`)) continue;
    const link = buildLink(item);
    if (anchor && anchor.parentNode === host) host.insertBefore(link, anchor);
    else host.appendChild(link);
  }
}

let timer = 0;
function schedule() {
  window.clearTimeout(timer);
  timer = window.setTimeout(inject, OBSERVE_DEBOUNCE_MS);
}

function start() {
  inject();
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
  start();
}
