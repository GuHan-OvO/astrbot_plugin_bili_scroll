#!/usr/bin/env python3
"""在陪伴小屋的 3D 场景里，给茶几加一台手机。

为什么是脚本而不是 patch：
``assets/voxel-room.js`` 是**单行**打包产物（677 KB），任何改动都会让 diff 显示整行，
patch 文件会变成近 700 KB 且不可读。所以这里用幂等的字符串插入代替 patch。

用法::

    python companion-lobby-phone.py <陪伴插件根目录>
    python companion-lobby-phone.py <陪伴插件根目录> --check   # 只看会不会改，不落盘

改动三处：

1. ``pages/陪伴小屋/assets/voxel-room.js``（生效）：茶几白块之后插入机身 + 屏幕
2. ``pages/陪伴小屋/assets/voxel-source/panels/home-room-3d.source.js``（源码，保持可重现）
3. ``pages/陪伴小屋/index.html``：升 ``?v=`` 缓存号，否则浏览器继续用旧 bundle

重复运行是安全的：已含有手机代码就跳过。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 茶几白块那段的句尾，bundle 与 source 都用它定位
ANCHOR_BUNDLE = "M(se.stool,d,.9,.02,.13,.015,.13,u.edge);"
ANCHOR_SOURCE = "block(groups.stool, x, .90, .02, .13, .015, .13, C.edge);"

# 手机：机身贴桌面，屏幕是机身顶面的一层薄片
BUNDLE_PHONE = (
    ANCHOR_BUNDLE
    + "M(Mt,.34,.785,.14,.07,.02,.30,u.edge),"
    + 'M(Mt,.34,.797,.14,.056,.004,.26,"#8fd3ff");'
)
SOURCE_PHONE_LINES = [
    "    // 茶几上放一台手机。注意：本目录（voxel-source）不参与运行时，实际生效的是",
    "    // assets/voxel-room.js（打包产物）里同一处代码；两处需保持一致。",
    "    block(groups.stool, .34, .785, .14, .07, .02, .30, C.edge);",
    '    block(groups.stool, .34, .797, .14, .056, .004, .26, "#8fd3ff");',
]

VERSION_RE = re.compile(r"voxel-room\.js\?v=([A-Za-z0-9._-]+)")
NEW_VERSION = "home-v2-entrance-20261024"


def patch_bundle(path: Path, check: bool) -> str:
    src = path.read_text(encoding="utf-8")
    if BUNDLE_PHONE in src:
        return "bundle: 已含手机，跳过"
    if src.count(ANCHOR_BUNDLE) != 1:
        raise SystemExit(f"bundle 锚点命中 {src.count(ANCHOR_BUNDLE)} 次，拒绝修改")
    if not check:
        path.write_text(src.replace(ANCHOR_BUNDLE, BUNDLE_PHONE, 1), encoding="utf-8")
    return "bundle: 将插入手机模型" + ("（check，未落盘）" if check else "")


def patch_source(path: Path, check: bool) -> str:
    lines = path.read_bytes().splitlines(keepends=True)
    eol = b"\r\n" if lines[0].endswith(b"\r\n") else b"\n"
    text = path.read_text(encoding="utf-8")
    if "#8fd3ff" in text:
        return "source: 已含手机，跳过"
    anchor = next(
        (i for i, l in enumerate(lines) if l.strip() == ANCHOR_SOURCE.encode("utf-8")), None
    )
    if anchor is None:
        raise SystemExit("source 里找不到茶几白块那行，拒绝修改")
    # 插在那段 for 循环结束的 "}" 之后
    insert_at = anchor + 1
    while insert_at < len(lines) and lines[insert_at].strip() != b"}":
        insert_at += 1
    if insert_at >= len(lines):
        raise SystemExit("source 结构不符合预期（找不到 for 循环结尾）")
    if not check:
        block = b"".join(l.encode("utf-8") + eol for l in SOURCE_PHONE_LINES)
        path.write_bytes(b"".join(lines[: insert_at + 1]) + block + b"".join(lines[insert_at + 1 :]))
    return "source: 将插入镜像代码" + ("（check，未落盘）" if check else "")


def patch_index(path: Path, check: bool) -> str:
    src = path.read_text(encoding="utf-8")
    matches = VERSION_RE.findall(src)
    if not matches:
        raise SystemExit("index.html 里找不到 voxel-room.js?v= 版本号")
    if all(v == NEW_VERSION for v in matches):
        return f"index.html: 版本号已是 {NEW_VERSION}，跳过"
    if not check:
        path.write_text(VERSION_RE.sub(f"voxel-room.js?v={NEW_VERSION}", src), encoding="utf-8")
    return f"index.html: 将把 {len(matches)} 处版本号改为 {NEW_VERSION}" + (
        "（check，未落盘）" if check else ""
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="给陪伴小屋茶几加一台手机")
    parser.add_argument("companion_root", help="陪伴插件根目录")
    parser.add_argument("--check", action="store_true", help="只报告，不写文件")
    args = parser.parse_args()

    root = Path(args.companion_root)
    page = root / "pages" / "陪伴小屋"
    targets = {
        "bundle": (page / "assets" / "voxel-room.js", patch_bundle),
        "source": (page / "assets" / "voxel-source" / "panels" / "home-room-3d.source.js", patch_source),
        "index": (page / "index.html", patch_index),
    }
    for name, (path, handler) in targets.items():
        if not path.is_file():
            raise SystemExit(f"找不到 {name}: {path}")
        print(handler(path, args.check))
    print("完成" + ("（未写任何文件）" if args.check else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
