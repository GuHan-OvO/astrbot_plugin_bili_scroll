// 把「看过的视频」「自检」加到 BiliBot 控制中心的左侧导航里。
//
// 三个关键点：
// 1. 侧边栏是 app.js 里一大段模板字符串拼的、每次切页都会重建，所以用 MutationObserver
//    等它渲染完再补，重建一次补一次，不 hook 任何内部函数。
// 2. 图标必须直接用上游 icons.js 的 `icon()`：`.nav-item span { flex: 1 }` 会把
//    任何 span 撑开——用 <span> 包图标会把文字挤到最右边。
// 3. 跳转要绕：插件页面可能跑在 iframe 里，改自己的 hash 无效；改 window.top 的 hash
//    又可能被 sandbox 静默拦掉（不抛错也不生效），所以回读确认，失败退回开新标签。

import { icon } from "./icons.js";

const PAGES = [
  { page: "history", label: "看过的视频", icon: "video" },
  { page: "selftest", label: "自检", icon: "refresh" },
];

const VERIFY_DELAY_MS = 400;
const OBSERVE_DEBOUNCE_MS = 120;

function pluginId() {
  const matched = location.pathname.match(/\/api\/plugin\/page\/content\/([^/]+)\//);
  return matched ? matched[1] : "astrbot_plugin_bili_scroll";
}

function targetHash(page) {
  return `#/plugin-page/${pluginId()}/${page}`;
}

function targetUrl(page) {
  return `${location.origin}/${targetHash(page)}`;
}

function openInNewTab(page) {
  const opened = window.open(targetUrl(page), "_blank", "noopener");
  if (!opened) {
    window.prompt("页面跳转被拦住了，复制地址后手动打开：", targetUrl(page));
  }
}

function navigate(page) {
  const hash = targetHash(page);
  let top = null;
  try {
    top = window.top;
  } catch (err) {
    top = null;
  }

  if (!top || top === window) {
    location.hash = hash;
    return;
  }

  try {
    top.location.hash = hash;
  } catch (err) {
    openInNewTab(page);
    return;
  }

  // sandbox 里赋值既不抛错也不生效，回读确认一次
  window.setTimeout(() => {
    let applied = false;
    try {
      applied = top.location.hash === hash;
    } catch (err) {
      applied = false;
    }
    if (!applied) openInNewTab(page);
  }, VERIFY_DELAY_MS);
}

function buildButton(item) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "nav-item";
  button.dataset.siblingPage = item.page;
  button.title = targetUrl(item.page);

  // 与上游同构：svg 直接是 button 的子元素，文字单独一个 span（span 会 flex:1）
  button.innerHTML = `${icon(item.icon, "nav-icon")}<span></span>`;
  button.querySelector("span").textContent = item.label;

  button.addEventListener("click", () => navigate(item.page));
  return button;
}

function inject() {
  const navList = document.querySelector("#sidebar .nav-list");
  if (!navList) return;

  for (const item of PAGES) {
    if (navList.querySelector(`[data-sibling-page="${item.page}"]`)) continue;
    navList.appendChild(buildButton(item));
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
