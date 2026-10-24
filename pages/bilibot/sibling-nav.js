// 在 BiliBot 控制中心右上角挂一个「其他页面」小导航。
//
// 为什么不改 app.js：侧边栏是 app.js 里一大段模板字符串拼的，往里面插东西容易碰坏。
//
// 为什么跳转要绕这么多：插件页面可能跑在 iframe 里（AstrBot 的 SPA 用
// `#/plugin-page/<插件>/<页面>` 切页），而 iframe 内改自己的 hash 无效；
// 改 `window.top.location.hash` 又可能被 sandbox 静默拦掉（不抛错、也不生效）。
// 所以：先试改 top 的 hash，短延时后**回读确认**，没生效就退回开新标签页。

(function () {
  const PAGES = [
    { page: "history", label: "看过的视频" },
    { page: "selftest", label: "自检" },
  ];
  const VERIFY_DELAY_MS = 400;

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
      // 弹窗也被拦了，只能把地址给出去
      window.prompt("这个页面被浏览器拦住了，复制地址后手动打开：", targetUrl(page));
    }
  }

  function navigate(page) {
    const hash = targetHash(page);
    const top = (() => {
      try {
        return window.top;
      } catch (err) {
        return null; // 跨域访问被拒
      }
    })();

    if (!top || top === window) {
      // 自己就是顶层（独立窗口打开），直接改自己的 hash
      location.hash = hash;
      return;
    }

    try {
      top.location.hash = hash;
    } catch (err) {
      console.warn("[bilibot-nav] 无法改父窗口地址，改用新标签：", err);
      openInNewTab(page);
      return;
    }

    // sandbox 拦掉时赋值不抛错也不生效，所以回读确认一次
    window.setTimeout(() => {
      let applied = false;
      try {
        applied = top.location.hash === hash;
      } catch (err) {
        applied = false;
      }
      if (!applied) {
        console.warn("[bilibot-nav] 父窗口地址没有变化，改用新标签");
        openInNewTab(page);
      }
    }, VERIFY_DELAY_MS);
  }

  function mount() {
    if (!document.body || document.getElementById("bilibot-sibling-nav")) return;

    const style = document.createElement("style");
    style.textContent = `
      #bilibot-sibling-nav {
        position: fixed;
        top: 10px;
        right: 12px;
        z-index: 60;
        display: flex;
        gap: 6px;
        padding: 4px;
        border-radius: 999px;
        background: color-mix(in srgb, var(--surface, #fff) 88%, transparent);
        border: 1px solid var(--line, #e3e8f0);
        box-shadow: 0 4px 16px rgb(0 0 0 / 8%);
        backdrop-filter: blur(8px);
      }
      #bilibot-sibling-nav button {
        font: inherit;
        font-size: 12px;
        line-height: 1.4;
        padding: 4px 12px;
        border: none;
        border-radius: 999px;
        background: transparent;
        color: var(--muted, #6b7789);
        cursor: pointer;
      }
      #bilibot-sibling-nav button:hover {
        background: color-mix(in srgb, var(--accent, #3b82f6) 14%, transparent);
        color: var(--accent, #3b82f6);
      }
      @media (max-width: 560px) {
        #bilibot-sibling-nav { top: 6px; right: 6px; }
        #bilibot-sibling-nav button { padding: 3px 10px; font-size: 11px; }
      }
    `;

    const nav = document.createElement("nav");
    nav.id = "bilibot-sibling-nav";
    nav.setAttribute("aria-label", "其他页面");
    for (const item of PAGES) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.label;
      button.title = targetUrl(item.page);
      button.addEventListener("click", () => navigate(item.page));
      nav.appendChild(button);
    }

    document.head.appendChild(style);
    document.body.appendChild(nav);
    console.info(
      `[bilibot-nav] 已挂载，插件 id = ${pluginId()}，目标 = ${targetUrl(PAGES[0].page)}`
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
