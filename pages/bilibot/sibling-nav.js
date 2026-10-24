// 把「看过的视频」「自检」加到 BiliBot 控制中心的左侧导航里。
//
// 三个关键点：
// 1. 侧边栏是 app.js 里一大段模板字符串拼的、每次切页都会重建，所以用 MutationObserver
//    等它渲染完再补，重建一次补一次，不 hook 任何内部函数。
// 2. 图标必须直接用上游 icons.js 的 `icon()`：`.nav-item span { flex: 1 }` 会把
//    任何 span 撑开——用 <span> 包图标会把文字挤到最右边。
// 3. 跳转**用 <a target="_top"> 而不是 JS 改 hash**：插件页面可能跑在 iframe 里，
//    脚本改 window.top.location.hash 会被 sandbox 静默拦掉（不抛错也不生效）；
//    而 target="_top" 是浏览器原生行为，由页面框架决定处理方式，不受脚本沙箱影响。

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

function injectStyle() {
  if (document.getElementById("bilibot-sibling-style")) return;
  const style = document.createElement("style");
  style.id = "bilibot-sibling-style";
  // a 标签复用了 button 的 .nav-item 样式，这里只需要去掉下划线、保持可点击
  style.textContent = `
    #sidebar a.nav-item { text-decoration: none; cursor: pointer; }
    #sidebar a.nav-item:visited { color: #657085; }
  `;
  document.head.appendChild(style);
}

function inject() {
  const navList = document.querySelector("#sidebar .nav-list");
  if (!navList) return;
  injectStyle();

  // 插到「基础设置」之前。找不到锚点（上游改了导航项）就退回追加到末尾，至少不会消失。
  const anchor = navList.querySelector('[data-page="basics"]');

  for (const item of PAGES) {
    if (navList.querySelector(`[data-sibling-page="${item.page}"]`)) continue;
    const link = buildLink(item);
    if (anchor && anchor.parentNode === navList) {
      navList.insertBefore(link, anchor);
    } else {
      navList.appendChild(link);
    }
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
