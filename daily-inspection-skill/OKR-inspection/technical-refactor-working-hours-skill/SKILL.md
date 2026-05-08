---
name: technical-refactor-working-hours-inspection
description: 巡检 InsightEngine 技术改造工时占比指标；页面自动化脚本在查询后直接从目标卡片表格第一行提取当天数据并生成每日 JSON，JoyClaw 负责读取历史 JSON 与生成本周趋势 JSON。
---

# technical-refactor-working-hours-inspection

## 目标

巡检目标卡片：

**技术改造工时占比-周（5->4）-汇总-C3维度**

固定部门：

**支付方案研发部**

## 自动化执行

从本 skill 根目录运行：

```bash
/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python scripts/run_skill.py
```

脚本只负责打开固定页面，收起侧边栏，定位目标卡片，打开图表筛选，设置：

- 填报日期：上周五到今天
- 填报人部门C3：支付方案研发部

查询完成后，脚本会保存截图，并直接从目标卡片表格第一行提取当天数据，写入：

```text
out/history/YYYY-MM-DD.json
out/05_after_query.png
```

当天 JSON 字段固定对齐 HTML 所需结构：

- `total_working_hours`
- `technical_refactor_working_hours`
- `technical_refactor_working_hours_rate`

不要分析其他卡片或页面其他区域。

## 每日结果

每天巡检后，脚本写入：

```text
out/history/YYYY-MM-DD.json
```

每日 JSON 只保留这 3 个指标：

- `total_working_hours`：总工时或填报工时，单位 `hour`
- `technical_refactor_working_hours`：技术改造工时，单位 `hour`
- `technical_refactor_working_hours_rate`：技术改造工时占比，单位 `%`

格式：

```json
{
  "date": "2026-04-17",
  "indicator_type": "technical_refactor_working_hours",
  "indicator_name": "技术改造工时占比-周（5->4）-汇总-C3维度",
  "department_c3": "支付方案研发部",
  "status": "success",
  "metrics": {
    "total_working_hours": 120.5,
    "technical_refactor_working_hours": 18.0,
    "technical_refactor_working_hours_rate": 14.9
  },
  "unit": {
    "total_working_hours": "hour",
    "technical_refactor_working_hours": "hour",
    "technical_refactor_working_hours_rate": "%"
  },
  "source": {
    "query_screenshot": "out/05_after_query.png"
  }
}
```

表格提取规则：

- 只读取目标卡片表格第一行。
- 表头 `总工时（人天）` 映射为 `total_working_hours`。
- 表头 `技术改造工时（人天）` 映射为 `technical_refactor_working_hours`。
- 表头 `技术改造工时占比` 映射为 `technical_refactor_working_hours_rate`。
- 百分比必须转成数字类型，例如 `0.69%` 写成 `0.69`。
- 表格原文案虽然是“人天”，但 JSON 字段名保持 HTML 既有结构，不改字段名。

如果表格无法读取，脚本仍写入当天文件，`status` 设为 `failed`，`metrics` 中无法识别的值写 `null`，并增加 `error` 说明。

## 本周趋势

JoyClaw 只读取脚本已生成的 `out/history/` 中本周 JSON，按日期升序输出本周截止当前日期的趋势 JSON。

当天数据必须直接读取：

```text
out/history/YYYY-MM-DD.json
```

如果 `out/history/` 不存在、为空，或缺少本周日期，不要从截图补数据，也不要生成 `out/weekly-trend-from-screenshot.json`。只汇总已有每日 JSON；缺少当天 JSON 时，将该指标状态标为 `missing` 或 `partial`，并在 `notes` 中说明缺失日期。

```json
{
  "skill_name": "technical-refactor-working-hours-inspection",
  "indicator_type": "technical_refactor_working_hours",
  "indicator_name": "技术改造工时占比-周（5->4）-汇总-C3维度",
  "department_c3": "支付方案研发部",
  "time_range": {
    "start_date": "2026-04-13",
    "end_date": "2026-04-17"
  },
  "status": "success",
  "history": {
    "total_working_hours": [
      { "date": "2026-04-17", "value": 120.5, "unit": "hour" }
    ],
    "technical_refactor_working_hours": [
      { "date": "2026-04-17", "value": 18.0, "unit": "hour" }
    ],
    "technical_refactor_working_hours_rate": [
      { "date": "2026-04-17", "value": 14.9, "unit": "%" }
    ]
  },
  "summary": "已汇总本周技术改造工时占比核心指标历史数据。"
}
```

## 输出约束

- 只输出 JSON，不输出解释性文字。
- 数值用数字类型，不要带 `%`、`,` 或中文单位。
- 历史趋势只使用每日 JSON；不要从截图抽取技术改造工时占比数据。
- 不要编造缺失日期或不可见数值。
- 如需周五清理历史文件，必须在总报告生成并确认落盘后再清理。
