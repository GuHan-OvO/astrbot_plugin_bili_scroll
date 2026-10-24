# 与「陪伴」插件的对接



本目录放**对方仓库需要的改动**，做成 patch，不打进本仓库的代码里。



## 背景



`astrbot_plugin_private_companion` 从 **7.0.0** 起换成了 provider 发现机制

（`astrbot_host/integration_registry.py::_provider()`）：



- 它遍历 `astrbot_host/integration_catalog.py` 的 `EXTERNAL_PROVIDERS`，

  对登记过的 `plugin_id` 去找对应插件；

- 找到后读 `插件实例.extension_api`，调用**同步**的 `companion_v2_status()`，

  校验 `schema` / `plugin_id` / `enabled` / `runtime_ready`；

- 通过后把该插件记进后端 manifest（`/integration/manifest` 的 `providers`），
  并把该插件的 `pages/` 目录扫进 `pages` 字段（仅元数据）。

> **7.0.0 的实际限制**：小屋界面（`pages/陪伴小屋/app.js`）的家具目录是**前端硬编码的 14 项**，
> `room_furniture_catalog()` 后端已实现但前端未接入，`panel_id` 在前端零引用。
> 所以打完补丁后，本插件**只在后端 manifest 里可见，小屋界面上不显示**。



**它不会自动扫描所有插件**，所以必须先在 catalog 里登记。本仓库侧已实现

`core/extension_api.py`（只读门面）+ `main.py` 里挂载 `self.extension_api`。



## 补丁改了三个文件



| 文件 | 改动 | 必要性 |

|---|---|---|

| `astrbot_host/integration_catalog.py` | `EXTERNAL_PROVIDERS` 加一项：`plugin_id` / `capability_id` / `label`（我会自己刷B站）/ `description` / `furniture` | **必需**，不加就完全不出现在面板 |

| `astrbot_host/native_extensions/together/media_methods.py` | 插件名白名单 `('astrbot_plugin_bili_scroll', ...)` | **必需**，陪伴靠它找到本插件实例调 `check_cookie` 等 |

| `astrbot_host/native_extensions/live/settings-schema.json` | 一处 hint 文案里的包名 | 仅文案，不影响功能 |



## 什么时候打



**前提：陪伴插件已经是 7.0.0**（`metadata.yaml` 里 `version: 7.0.0`）。6.x 没有这套机制，打了也没用。



## 怎么打



```bash

cd <陪伴插件仓库目录>

git apply --ignore-whitespace --check patches/private-companion-7.0.0-bili-scroll.patch

git apply --ignore-whitespace patches/private-companion-7.0.0-bili-scroll.patch

```



> **必须带 `--ignore-whitespace`**：市场分发的文件与 GitHub 上的空白/行尾有差异，

> 不忽略时 `git apply` 会报 "patch does not apply"。



撤销：`git apply --reverse --ignore-whitespace patches/private-companion-7.0.0-bili-scroll.patch`



## 如果打不上



上游还是 `test.alpha`，随时可能改这些文件。打不上就手工加——三处都只有一两行：



1. `integration_catalog.py` 的 `EXTERNAL_PROVIDERS` 元组末尾：



```python

    {

        "plugin_id": "astrbot_plugin_bili_scroll",

        "capability_id": "bili_scroll",

        "label": "我会自己刷B站",

        "description": "定时刷 B站、挑片、在评论区 @ 主人；执行仍由该插件自己完成。",

        "furniture": {"id": "bili-scroll", "name": "B站电视台", "panel_id": "bili-scroll"},

    },

```



2. `media_methods.py` 里 `for name in (...)` 的第一个元素改成 `'astrbot_plugin_bili_scroll'`

3. `settings-schema.json` 里那句中 `astrbot_plugin_bilibili_ai_bot` 改成 `astrbot_plugin_bili_scroll`



`plugin_id` 必须与两边完全一致（本仓库 `core/extension_api.py` 的 `PLUGIN_ID`）。



## 验证



重启陪伴插件后，「陪伴小屋」应出现 **我会自己刷B站**，

状态 `connected`（插件侧 `ENABLE_PROACTIVE` 打开且配了 `SESSDATA` 时）。



| 现象 | 原因 |

|---|---|

| `disabled` | 本插件 `ENABLE_PROACTIVE` 关着 |

| `waiting` | 没配 `SESSDATA`（`runtime_ready=False`） |

| `missing` | 插件没装，或 `plugin_id` 与目录名不一致 |

| `degraded` | `companion_v2_status()` 返回不合法 |

| 根本不出现 | 陪伴还是 6.x，或 patch 没打进 `EXTERNAL_PROVIDERS` |
| manifest 里有但界面看不到 | **正常现象**，7.0.0 前端不渲染外部 provider |

