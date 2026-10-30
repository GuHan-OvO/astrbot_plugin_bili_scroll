"""前端契约回归：弹层可见性、内嵌视图令牌继承。

这些是「看 HTML 字符串就能判定」的契约，不依赖浏览器；之所以写成测试，
是因为它们都是**漏一处就静默失效**的写法：

* `.modal-backdrop` 默认 `opacity: 0`，只有 `is-visible` 才显示。
  `confirmModal` 曾经漏加，结果点「重新生成今日计划」后整页压暗、弹窗透明、
  透明遮罩吃掉全部点击（用户实测报告）。
* 内嵌视图如果在 `:host` 里重抄一套颜色令牌，会盖掉宿主继承，
  宿主换主题后这两页不跟随。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "pages" / "bilibot" / "app.js"


def app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index("\n}", start)
    return source[start:end]


def test_confirm_modal_opens_its_backdrop():
    block = function_block(app_source(), "confirmModal")
    assert 'class="modal-backdrop"' in block
    assert "is-visible" in block


def test_overlay_depth_has_visibility_fallback():
    block = function_block(app_source(), "bindOverlayDepth")
    # 任何写进 #modal-root 的遮罩都应由观察器补上 is-visible，
    # 避免以后新增弹层又忘记加类。
    assert "modal-backdrop" in block
    assert 'classList.add("is-visible")' in block
    assert "isConnected" in block


def test_embedded_views_do_not_redefine_host_color_tokens():
    for name in ("history.js", "selftest.js"):
        source = (ROOT / "pages" / "bilibot" / "views" / name).read_text(encoding="utf-8")
        host_start = source.index(":host {")
        host_end = source.index("}", host_start)
        host_block = source[host_start:host_end]
        for token in ("--accent:", "--text:", "--surface:", "--line:", "--shadow-"):
            assert token not in host_block, f"{name} 的 :host 重抄了 {token}，会盖掉宿主令牌"
        # 只保留别名映射
        assert "--text-2: var(--text-secondary)" in host_block
