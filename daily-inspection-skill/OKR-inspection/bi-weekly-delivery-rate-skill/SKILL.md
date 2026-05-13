---
name: bi-weekly-delivery-rate-inspection
description: 巡检 InsightEngine 双周交付率指标；页面自动化脚本查询后 hover 图表 canvas，从 tooltip 提取双周交付率，并生成每日 JSON。
---

# bi-weekly-delivery-rate-inspection

## 目标

巡检目标指标：

**双周交付率**

固定部门：

**支付方案研发部**

## 自动化执行

从本 skill 根目录运行：

```bash
"${XUNJIAN_PYTHON:-python3}" scripts/run_skill.py
```

脚本负责打开固定页面，收起侧边栏，设置：

- 快照日期：保留页面默认最新日
- 卡片完成日期：上周五到今天
- 任务处理人部门C3：支付方案研发部

查询完成后，脚本保存截图：

```text
out/03_after_query.png
```

然后依次 hover 页面中的 ECharts canvas，读取 tooltip 文案中的：

```text
双周交付率：67.65%
```

并写入当天每日 JSON。只提取“双周交付率”这一个指标，不读取其他无关图表。

## 每日结果

每天巡检后，脚本写入：

```text
out/history/YYYY-MM-DD.json
```

每日 JSON 只保留这 1 个指标：

- `biweekly_delivery_rate`：双周交付率，单位 `%`

格式：

```json
{
  "date": "2026-04-17",
  "indicator_type": "bi_weekly_delivery_rate",
  "indicator_name": "双周交付率",
  "department_c3": "支付方案研发部",
  "status": "success",
  "metrics": {
    "biweekly_delivery_rate": 80.0
  },
  "unit": {
    "biweekly_delivery_rate": "%"
  },
  "source": {
    "query_screenshot": "out/03_after_query.png"
  }
}
```

如果页面 tooltip 文案与上面略有差异，按“双周交付率”的可见含义映射到上述固定 JSON 字段；不要改字段名。不要再输出完成需求数、总需求数、双周内交付需求数等额外字段。

## 本周趋势

JoyClaw 优先读取 `out/history/` 中本周已有 JSON，按日期升序输出本周截止当前日期的趋势 JSON。

如果当天 JSON 缺失，应优先重新运行本脚本，不要从截图估算数值。

```json
{
  "skill_name": "bi-weekly-delivery-rate-inspection",
  "indicator_type": "bi_weekly_delivery_rate",
  "indicator_name": "双周交付率",
  "department_c3": "支付方案研发部",
  "time_range": {
    "start_date": "2026-04-13",
    "end_date": "2026-04-17"
  },
  "status": "success",
  "history": {
    "biweekly_delivery_rate": [
      { "date": "2026-04-17", "value": 80.0, "unit": "%" }
    ]
  },
  "summary": "已汇总本周双周交付率核心指标历史数据。"
}
```

## 输出约束

- 只输出 JSON，不输出解释性文字。
- 数值用数字类型，不要带 `%`、`,` 或中文单位。
- 历史趋势使用每日 JSON；每日 JSON 缺失时优先重跑本脚本。
- 不要编造缺失日期或不可见数值。
- 如需周五清理历史文件，必须在总报告生成并确认落盘后再清理。
