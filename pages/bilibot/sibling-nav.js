// 在 BiliBot 控制中心右上角挂一个「其他页面」小导航。
//
// 为什么单独成文件、自己注入样式：
// 控制中心的侧边栏是 app.js 里一大段模板字符串拼的，往里面插东西容易碰坏；
// 而页面之间跳转要走 AstrBot 的 SPA 路由（#/plugin-page/<插件>/<页面>），
// 插件页面本身在 iframe 里，改自己的 hash 没用，必须改 window.top。
//
// 插件 id 从当前 iframe 的路径里解析，所以改包名后这里不用跟着改。

(function () {
  const PAGES = [
    { page: "history", label: "看过的视频" },
    { page: "selftest", label: "自检" },
  ];

  function pluginId() {
    const matched = location.pathname.match(/\/api\/plugin\/page\/content\/([^/]+)\//);
    return matched ? matched[1] : "astrbot_plugin_bili_scroll";
  }

  function openPage(page) {
    const hash = `#/plugin-page/${pluginId()}/${page}`;
    try {
      window.top.location.hash = hash;
    } catch (err) {
      // 跨域或被沙箱限制时退回改自己的地址，至少不会静默失败
      location.hash = hash;
    }
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
      button.addEventListener("click", () => openPage(item.page));
      nav.appendChild(button);
    }

    document.head.appendChild(style);
    document.body.appendChild(nav);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
