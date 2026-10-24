# 与「陪伴」插件的对接

本目录放**对方仓库需要的一行改动**，做成 patch，不打进本仓库的代码里。

## 背景

`astrbot_plugin_private_companion` 从 **7.0.0** 起换成了 provider 发现机制
（`astrbot_host/integration_registry.py::_provider()`）：

- 它会遍历 `astrbot_host/integration_catalog.py` 里的 `EXTERNAL_PROVIDERS`，
  对登记过的 `plugin_id` 去找对应的已安装插件；
- 找到后读 `插件实例.extension_api`，调用**同步**的 `companion_v2_status()`，
  校验 `schema`/`plugin_id`/`enabled`/`runtime_ready`；
- 通过后，在「陪伴小屋」里显示为已接入，并把该插件的 `pages/` 目录登记为面板。

**它不会自动扫描所有插件**，所以必须先在它的 catalog 里登记一行。

本仓库这边已经实现好了：`core/extension_api.py`（只读门面）+ `main.py` 里挂载
`self.extension_api`。

## 什么时候打这个 patch

**前提：陪伴插件已经是 7.0.0**（`metadata.yaml` 里 `version: 7.0.0`）。
6.7.0 及以前没有这套机制，打上去也没用。

## 怎么打

```bash
cd <陪伴插件仓库目录>
git apply --check patches/private-companion-7.0.0-bili-scroll.patch   # 先干跑
git apply patches/private-companion-7.0.0-bili-scroll.patch
```

或者用 `patch -p1 < ...patch`。

撤销：

```bash
git apply --reverse patches/private-companion-7.0.0-bili-scroll.patch
```

## 如果打不上

7.0.0 还是 `test.alpha`，上游随时可能改这个文件导致上下文对不上。
实在打不上就手工加——改动只有一段，加在 `EXTERNAL_PROVIDERS` 元组的末尾：

```python
    {
        "plugin_id": "astrbot_plugin_bilibili_ai_bot",
        "capability_id": "bili_scroll",
        "label": "刷B站",
        "description": "定时刷 B站、挑片、在评论区 @ 主人；执行仍由该插件自己完成。",
        "furniture": {"id": "bili-scroll", "name": "B站电视台", "panel_id": "bili-scroll"},
    },
```

`plugin_id` 必须与两边完全一致（本仓库 `core/extension_api.py` 里的 `PLUGIN_ID`）。

## 验证

打完 patch、重启陪伴插件后，打开「陪伴小屋」的集成/能力列表，应该出现一项
**刷B站**，状态为 `connected`（插件侧 `ENABLE_PROACTIVE` 打开且已配置 SESSDATA 时）。

状态不连通时的常见原因：

| 现象 | 原因 |
|---|---|
| 显示 `disabled` | 本插件 `ENABLE_PROACTIVE` 是关的 |
| 显示 `waiting` | 没配 `SESSDATA`（`runtime_ready=False`） |
| 显示 `missing` | 插件没装，或 `plugin_id` 与目录名不一致 |
| 显示 `degraded` | `companion_v2_status()` 返回不合法（schema/plugin_id/类型不对） |
| 根本不出现 | 陪伴还是 6.x，或 patch 没打进 `EXTERNAL_PROVIDERS` |
