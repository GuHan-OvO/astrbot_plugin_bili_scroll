// 把「看过的视频」「自检」加到 BiliBot 控制中心的左侧导航里。
//
// 为什么不直接改 app.js：侧边栏是 app.js 里一大段模板字符串拼的（每次切页都会重建），
// 往里插东西容易碰坏上游逻辑。这里用 MutationObserver 等它渲染完再追加，
// 重建一次就补一次，不需要 hook 任何内部函数。
//
// 为什么跳转要绕：插件页面可能跑在 iframe 里，改自己的 hash 无效；
// 改 `window.top.location.hash` 又可能被 sandbox 静默拦掉（不抛错、也不生效）。
// 所以：先试改 top，短延时后回读确认，没生效就开新标签。

(function () {
  const PAGES = [
    {
      page: "history",
      label: "看过的视频",
      svg: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    },
    {
      page: "selftest",
      label: "自检",
      svg: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    },
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

    const iconSpan = document.createElement("span");
    iconSpan.className = "nav-icon";
    iconSpan.innerHTML =
      `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
      `stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${item.svg}</svg>`;
    button.appendChild(iconSpan);

    const label = document.createElement("span");
    label.textContent = item.label;
    button.appendChild(label);

    button.addEventListener("click", () => navigate(item.page));
    return button;
  }

  function inject() {
    const sidebar = document.querySelector("#sidebar");
    if (!sidebar) return;
    const navList = sidebar.querySelector(".nav-list");
    if (!navList) return;

    // 上游每次重建 sidebar 都会换掉 navList，所以按「里面有没有我们的按钮」来判断
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
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
