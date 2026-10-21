# 自主查询测试日志（2026-10-21，v1.7.1）

**环境：本地离线模拟。** 以下记录由实际插件查询循环执行生成，但模型回答、B站数据和视频核查结果由测试替身提供；没有连接真实模型、B站或服务器，不能证明线上识别质量或接口兼容性。

流程模拟检验：逐项资料请求、证据回传、最终决定、总开关和失败处理。所有场景均未发送B站评论。毫秒级耗时只反映模拟调用，不能作为真实模型速度参考。

本轮完整回归：336 个 Python 测试通过、62 个子测试通过、2 个跳过；4 个界面测试通过；Python 编译检查、JavaScript 语法检查通过。执行命令：`python -m pytest tests -q`、`node --test tests/test_extension_ui.cjs`、`python -m compileall -q core main.py`、`node --check pages/bilibot/app.js`。

## 字幕 → 指定片段核查 → 生成回复

断言通过。以下为本次执行保存的流程记录：

```json
{
  "time": "2026-10-21T22:36:48",
  "oid": "123",
  "thread_id": "thread",
  "decision": "reply",
  "calls": [
    {
      "tool": "video_subtitles",
      "status": "ok",
      "cached": false,
      "seconds": 0.0,
      "reason": ""
    },
    {
      "tool": "video_inspect",
      "status": "ok",
      "cached": false,
      "seconds": 0.0,
      "reason": ""
    }
  ],
  "error": "",
  "mode": "comment"
}
```

## 查询成功后仍选择不回复

断言通过。以下为本次执行保存的流程记录：

```json
{
  "time": "2026-10-21T22:36:48",
  "oid": "123",
  "thread_id": "thread",
  "decision": "ignore",
  "calls": [
    {
      "tool": "web_search",
      "status": "ok",
      "cached": false,
      "seconds": 0.0,
      "reason": ""
    }
  ],
  "error": "",
  "mode": "comment"
}
```

## 字幕超时 → 回传失败 → 不回复

断言通过。以下为本次执行保存的流程记录：

```json
{
  "time": "2026-10-21T22:36:48",
  "oid": "123",
  "thread_id": "thread",
  "decision": "ignore",
  "calls": [
    {
      "tool": "video_subtitles",
      "status": "unavailable",
      "cached": false,
      "seconds": 0.0,
      "reason": "timeout"
    }
  ],
  "error": "",
  "mode": "comment"
}
```

## 总开关关闭 → 只作最终决定、不查询

断言通过。以下为本次执行保存的流程记录：

```json
{
  "time": "2026-10-21T22:36:48",
  "oid": "123",
  "thread_id": "thread",
  "decision": "reply",
  "calls": [],
  "error": "",
  "mode": "comment"
}
```

## 服务器实际验证

更新并重载插件，在 Web「回复与互动 → 回复前自主查询」开启总开关（默认开启）。在 AstrBot 原生插件配置中可搜索“自主查询总开关”。

管理员运行 `/bili测试查询 BV号`，先尝试简介查询；也可运行 `/bili测试查询 BV号 请检查30到60秒是否出现猫，并提供时间范围`。请填写真实BV号。调用使用服务器已配置的模型和资料接口；视频核查需要视觉提供商，联网搜索需要搜索服务。会产生正常模型调用费用。

结果会列出实际调用的资料、成功/无结果、缓存、耗时及最终决定，回复仅供预览，不发送B站评论、不修改好感或画像。用 `/bili日志 查询` 查看保存的记录。

若显示“未执行资料查询”，说明模型没有实际请求资料或提前失败，不能认为工具已经测通；“生成回复”也不代表已发布。接口报错、未配置能力或格式不正确会明确显示失败或不可用。

真实提供商、AstrBot 原生下拉界面及服务器运行验证：待维护者更新后执行。
