---
name: continuous-delivery-inspection
description: 巡检持续交付三项指标；页面脚本查询后直接从三张卡片元素提取值，生成当天 JSON，供总编排 HTML 报告集成展示。
---

# continuous-delivery-inspection

## 目标

持续交付脚本只提取这三个指标：

- `team_space_dev_test_online_requirements`：团队空间开发测试上线需求数
- `team_space_continuous_delivery_dev_test_online_requirements`：团队空间_持需交付_开发测试上线需求数
- `continuous_delivery_team_space_online_requirement_rate`：持续交付_团队空间上线需求占比

不要读取明细表、侧边栏、分页或其他无关字段。

## 自动化执行

从 `ContinuousDelivery-inspection` 目录运行：

```bash
"${XUNJIAN_PYTHON:-python3}" scripts/run_skill.py
```

脚本会直接完成：

- 打开持续交付页面。
- 进入“持续交付交付明细”。
- 筛选交付负责人部门到“支付方案研发部”。
- 点击查询。
- 从三个指标卡片元素读取当天值。
- 保存三张卡片截图：

```text
out/three_cards.png
```

并生成：

```text
out/continuous_delivery_YYYY-MM-DD.json
```

## JoyClaw 后续动作

JoyClaw 读取：

```text
ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json
```

当天 JSON 生成后，JoyClaw 必须立即完成两件事：

1. 校验三个字段、单位和日期是否完整。
2. 触发根目录总编排，把持续交付结果填充到统一 HTML 报告。

不要只保存截图，也不要只在对话里描述数值。JoyClaw 不要从 `out/three_cards.png` 视觉识别指标值，持续交付指标值只以当天 JSON 为准。

## 当天 JSON

脚本输出当天 JSON：

```text
ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json
```

格式：

```json
{
  "date": "2026-04-18",
  "indicator_type": "continuous_delivery",
  "indicator_name": "持续交付",
  "department_c3": "支付方案研发部",
  "status": "success",
  "metrics": {
    "team_space_dev_test_online_requirements": 62,
    "team_space_continuous_delivery_dev_test_online_requirements": 51,
    "continuous_delivery_team_space_online_requirement_rate": 82.26
  },
  "unit": {
    "team_space_dev_test_online_requirements": "count",
    "team_space_continuous_delivery_dev_test_online_requirements": "count",
    "continuous_delivery_team_space_online_requirement_rate": "%"
  },
  "source": {
    "query_screenshot": "out/three_cards.png"
  },
  "source_mode": "metric_cards_dom"
}
```

字段映射必须固定：

| 卡片标题 | JSON 字段 | 单位 |
| --- | --- | --- |
| 团队空间开发测试上线需求数 | `team_space_dev_test_online_requirements` | `count` |
| 团队空间_持需交付_开发测试上线需求数 | `team_space_continuous_delivery_dev_test_online_requirements` | `count` |
| 持续交付_团队空间上线需求占比 | `continuous_delivery_team_space_online_requirement_rate` | `%` |

## 填充总 HTML

当天 JSON 写入成功后，JoyClaw 从仓库根目录运行总编排：

```bash
"${XUNJIAN_PYTHON:-python3}" joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py
```

总编排会读取：

```text
ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json
```

并把它填入：

```text
joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
index.html
```

HTML 中持续交付区域必须展示：

- 三个指标的当天值。
- 总编排从 `ContinuousDelivery-inspection/out/three_cards.png` 复制到 `assets/screenshots/continuous_delivery.png` 后展示当天截图。
- JSON 状态；如果是 `partial` 或 `missing`，HTML 仍展示可用字段。

## 规则

- 数值必须是数字类型，百分比不要带 `%`。
- 指标值只读取 `ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json`；不要从截图补指标值。
- 如果某个值无法识别，写 `null`，`status` 写 `partial`，并增加 `error` 说明。
- 如果查询失败或截图不存在，写 `status: "failed"` 或 `status: "missing"`，三个指标值都写 `null`。
- JSON 文件日期使用当天日期。
- JSON 生成后必须进入总 HTML，不允许遗漏 `continuous_delivery` 字段。
