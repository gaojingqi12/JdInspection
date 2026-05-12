---
name: joyclaw-daily-inspection-orchestrator
description: 编排 JoyClaw 每日巡检 OKR、延期修复、AI、持续交付结果；先巡检 OKR、AI、持续交付，最后总编排按 OKR 延期数量触发修复并生成根目录总 HTML 报告。
---

# joyclaw-daily-inspection-orchestrator

## 根入口说明

当前文件是整个项目的总入口 skill，也是后续接手时优先阅读的主说明。

- 根目录 `SKILL.md`：总编排主入口。
- 根目录 `inspection-config.json`：统一配置巡检网址、关注卡片、关注指标、部门/团队、修复触发字段和在线报告地址；不要在脚本里新增硬编码巡检 URL 或关注指标。
- `joyclaw-daily-inspection-orchestrator-skill/`：总编排实现目录，保存模板、聚合脚本、输出产物。
- 单项 skill 目录：分别负责 OKR、AI、持续交付的页面自动化或数据补齐。

看全局时，先读当前文件，再看单项 skill 和聚合脚本。

## 统一配置文件

巡检 URL 和“要关注的内容”统一维护在：

```text
inspection-config.json
```

配置范围：

- `common`：固定部门、最终展示域名、在线报告地址。
- `okr`：OKR 四项巡检 URL、目标卡片、日期筛选项、部门筛选项、每日 JSON 指标 key、表格表头和单位。
- `ai`：AI 巡检 URL、下载卡片标题、目标人员名单、筛选字段和值。
- `continuous_delivery`：持续交付 URL、左侧菜单名、部门级联、三张指标卡片标题和输出字段。
- `repair`：延期提测/延期上线修复 URL、明细卡片、团队空间、延期状态字段、目标日期字段、触发指标。

脚本读取配置的公共入口是：

```text
inspection_config.py
```

后续如果巡检网址、卡片标题、关注指标、团队空间或在线报告地址变化，优先改 `inspection-config.json`；不要直接改 `scripts/run_skill.py`、修复目录 `config.py` 或 `aggregate_report.py` 里的业务常量。

## 适用场景

当用户要求 JoyClaw 自动巡检、生成日报/周趋势、或统一编排以下 skill 时，使用本 skill：

- `delay-test-rate-inspection`
- `delay-online-rate-inspection`
- `technical-refactor-working-hours-inspection`
- `bi-weekly-delivery-rate-inspection`
- `ai-non-deep-user-inspection`
- `continuous-delivery-inspection`
- `delayed-test-repair`
- `delayed-online-repair`

固定部门：**支付方案研发部**

## 总巡检顺序

必须先巡检 OKR，再巡检 AI，再巡检持续交付，最后运行总编排。总编排会读取当天 OKR JSON；如果延期提测需求数或延期上线需求数大于 0，会执行对应修复脚本，然后生成统一报告。

OKR 巡检顺序：

1. `OKR-inspection/delay-test-rate-skill`
2. `OKR-inspection/delay-online-rate-skill`
3. `OKR-inspection/technical-refactor-working-hours-skill`
4. `OKR-inspection/bi-weekly-delivery-rate-skill`

每个 OKR skill 目录下运行：

```bash
/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python scripts/run_skill.py
```

AI 巡检在 OKR 完成后执行，从仓库根目录的 `AI-inspection` 目录运行：

```bash
/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python scripts/run_skill.py
```

持续交付巡检在 AI 完成后执行，从仓库根目录的 `ContinuousDelivery-inspection` 目录运行：

```bash
/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python scripts/run_skill.py
```

## 职责边界

- `scripts/run_skill.py` 默认负责页面自动化：打开页面、设置筛选条件、点击查询、保存截图。
- `OKR-inspection/delay-test-rate-skill`、`OKR-inspection/delay-online-rate-skill`、`OKR-inspection/technical-refactor-working-hours-skill` 这三个脚本会在查询后直接从目标卡片表格第一行提取当天值，并写入 `out/history/YYYY-MM-DD.json`。
- 双周交付率脚本会在查询后 hover 图表 canvas，从 tooltip 提取 `双周交付率`，并写入 `out/history/YYYY-MM-DD.json`。
- OKR 部分：延期提测率、延期上线率、技术改造工时占比、双周交付率都读取脚本已生成的 `out/history/YYYY-MM-DD.json`，不从截图补数据。
- AI 部分：AI 脚本负责生成目标数据日的 `AI-inspection/out/non_deep_users_YYYY-MM-DD.json`，总编排从同一日期的源 JSON 派生非深度用户名单；周一巡检时 AI 日期取上周五，周二至周五取前一工作日，周末兜底取周五。如果已有 `AI-inspection/out/non_deep_user_names_YYYY-MM-DD.json`，可作为兜底读取。
- 持续交付脚本会在查询后直接从三张卡片元素提取三个指标，并生成 `ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json`。
- 总编排脚本 `aggregate_report.py` 读取各模块已经生成的 JSON，产出总 JSON 和 HTML；它不负责从截图识别 OKR 指标。
- 总编排脚本在读取当天 OKR JSON 后，如果 `delayed_test_requirements` 或 `delayed_online_requirements` 大于 0，必须执行对应修复目录的 `main.py`，再读取修复目录当天 `history/YYYY-MM-DD.json` 写入总 JSON 和 HTML。

## 数据读取规则

JoyClaw 必须按下面的数据源读取，不要混用：

| 模块 | 数据源 | 规则 |
| --- | --- | --- |
| 延期提测率 | `OKR-inspection/delay-test-rate-skill/out/history/YYYY-MM-DD.json` | 直接读当天和本周每日 JSON |
| 延期上线率 | `OKR-inspection/delay-online-rate-skill/out/history/YYYY-MM-DD.json` | 直接读当天和本周每日 JSON |
| 技术改造工时占比 | `OKR-inspection/technical-refactor-working-hours-skill/out/history/YYYY-MM-DD.json` | 直接读当天和本周每日 JSON |
| AI 巡检 | `AI-inspection/out/non_deep_users_YYYY-MM-DD.json` | 读取目标数据日源 JSON；周一读上周五，周二至周五读前一工作日，已有 `non_deep_user_names_YYYY-MM-DD.json` 时可兜底 |
| 持续交付 | `ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json` | 直接读当天 JSON |
| 双周交付率 | `OKR-inspection/bi-weekly-delivery-rate-skill/out/history/YYYY-MM-DD.json` | 脚本 hover 图表 tooltip 后直接生成 |
| 延期提测修复巡检 | `reschedule-delayed-test /history/YYYY-MM-DD.json` | 当天延期提测需求数大于 0 后执行并读取 |
| 延期上线修复巡检 | `repair-delayed-launch/history/YYYY-MM-DD.json` | 当天延期上线需求数大于 0 后执行并读取 |

约束：

- 延期提测率、延期上线率、技术改造工时占比、双周交付率、AI 巡检、持续交付都不允许从截图补指标值。
- 巡检目标是“本周变化趋势”，数据点只来自本周每日 JSON。
- 数值必须是数字类型，百分比不带 `%`。
- 无法识别的指标写 `null`，对应文件 `status` 写 `failed` 或 `partial` 并记录 `error`。

## 没有每日 JSON 时

如果延期提测率、延期上线率、技术改造工时占比、双周交付率、AI 巡检或持续交付缺少当天 JSON，不要从截图补数据。该模块在总报告中标为 `missing` 或 `partial`，并在 `notes` 或 `error` 中说明缺失文件。

双周交付率缺少当天 JSON 时，应优先重新运行 `OKR-inspection/bi-weekly-delivery-rate-skill/scripts/run_skill.py`，不要从截图估算数值。

## 四个每日 JSON 字段

延期提测率：

- `planned_test_requirements`
- `delayed_test_requirements`
- `delay_test_rate_okr`

延期上线率：

- `planned_online_requirements`
- `delayed_online_requirements`
- `delay_online_rate`

技术改造工时占比：

- `total_working_hours`
- `technical_refactor_working_hours`
- `technical_refactor_working_hours_rate`

双周交付率：

- `biweekly_delivery_rate`

## 延期修复触发

总编排读取当天 OKR JSON 后按下面规则处理：

- `OKR-inspection/delay-test-rate-skill/out/history/YYYY-MM-DD.json` 中 `metrics.delayed_test_requirements > 0` 时，从 `reschedule-delayed-test ` 目录运行 `/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python main.py`。
- `OKR-inspection/delay-online-rate-skill/out/history/YYYY-MM-DD.json` 中 `metrics.delayed_online_requirements > 0` 时，从 `repair-delayed-launch` 目录运行 `/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python main.py`。
- 修复脚本运行后读取对应 `history/YYYY-MM-DD.json`，合并 `results`、`clicked_items`、`modified_items`、`modify_failed_items`，生成 `repair_inspections`。
- 本地只想重新生成报告、不触发真实修复时，可以运行 `aggregate_report.py --skip-repair`，此时只展示已有修复 JSON。

`repair_inspections` 每项包含触发指标、脚本状态、修复目录 JSON 文件、成功明细和巡检状态。总 JSON 可保留失败明细、缺失字段明细和 `raw_json` 供排查；渲染 HTML 时必须隐藏 `raw_json`、本地源文件地址和空的失败/缺失明细。

统一报告 JSON 中增加：

```json
{
  "repair_inspections": [
    {
      "repair_type": "delayed_online",
      "title": "延期上线修复巡检",
      "trigger": {
        "metric_key": "delayed_online_requirements",
        "value": 1,
        "triggered": true
      },
      "json_file": "repair-delayed-launch/history/2026-04-18.json",
      "summary": {
        "巡检状态": "通过",
        "成功明细": []
      }
    }
  ]
}
```

## HTML 模板填充

HTML 模板固定使用：

```text
joyclaw-daily-inspection-orchestrator-skill/assets/weekly-line-report-template.html
```

聚合脚本负责读取 OKR 每日巡检 JSON、AI 当天人名结果 JSON、持续交付当天 JSON，并把模板中的：

```text
__JOYCLAW_WEEKLY_REPORT_JSON__
```

替换为本周报告 JSON。最终 HTML 会内置报告数据，但截图仍通过 `assets/screenshots/...` 相对路径引用，不内嵌 base64 图片。

只取当前自然周的数据：

- 本周起点：本周一。
- 本周终点：今天。
- 巡检最新日期：今天，写入报告 JSON 根字段 `inspection_date`。
- 忽略本周一之前的所有每日巡检 JSON，即使文件存在也不要放进 HTML。
- 不要补齐没有巡检 JSON 的日期；缺失日期不画点。

折线图规则：

- 延期提测需求卡片画 1 条线：从 `reschedule-delayed-test /history/*.json` 读取 `results.length`，表示 **收银台&内单交易域** 下按 `团队空间 = 支付生态研发部` 筛出的延期提测需求数；不要画 `支付方案研发部` OKR 汇总的计划提测需求数或延期提测率折线。
- 延期上线需求卡片画 1 条线：从 `repair-delayed-launch/history/*.json` 读取 `results.length`，表示 **收银台&内单交易域** 下按 `团队空间 = 支付生态研发部` 筛出的延期上线需求数；不要画 `支付方案研发部` OKR 汇总的计划上线需求数或延期上线率折线。
- 技术改造工时占比卡片画 1 条线：`technical_refactor_working_hours_rate`。
- 双周交付率卡片画 1 条线：`biweekly_delivery_rate`。
- HTML 模板支持点击折线或图例。点击后高亮该折线，并切换卡片顶部的最新值、最新日期。
- 卡片顶部“最新日期”必须展示 `inspection_date`，也就是当天巡检日期；不要用折线里最后一个数据点的日期替代。
- 不同单位的线条在同一图中按各自数值区间归一化绘制，展示值仍使用每日 JSON 中的原始值。

每个指标还要贴当天巡检截图。HTML 报告输出在：

```text
index.html
```

聚合脚本会把当天截图复制到报告输出目录下：

```text
assets/screenshots/
```

统一报告 JSON 中的截图路径必须使用报告内部相对路径，禁止写本机绝对路径、`file://` 路径或指向仓库外层目录的 `../../...` 路径。最终 HTML 直接通过 `assets/screenshots/...` 相对路径渲染图片，不要写入 `screenshot_base64url` / `query_screenshot_base64url`，也不要生成 `data:image/png;base64,...`。最终 HTML 页面不要展示原始文件地址。

| 指标 | HTML 中使用的截图路径 |
| --- | --- |
| 延期提测率 | `assets/screenshots/delay_test_rate.png` |
| 延期上线率 | `assets/screenshots/delay_online_rate.png` |
| 技术改造工时占比 | `assets/screenshots/technical_refactor_working_hours.png` |
| 双周交付率 | `assets/screenshots/bi_weekly_delivery_rate.png` |
| 持续交付 | `assets/screenshots/continuous_delivery.png` |

HTML 内置的报告 JSON 使用这个结构：

```json
{
  "generated_at": "2026-04-19 10:30:00",
  "inspection_date": "2026-04-19",
  "department_c3": "支付方案研发部",
  "time_range": {
    "start_date": "2026-04-13",
    "end_date": "2026-04-19"
  },
  "focus_series": [
    {
      "indicator_type": "delay_test_rate",
      "name": "延期提测率",
      "default_metric_key": "delay_test_rate_okr",
      "screenshot": "assets/screenshots/delay_test_rate.png",
      "screenshot_label": "当天巡检截图",
      "metrics": [
        {
          "key": "planned_test_requirements",
          "label": "计划提测需求数",
          "unit": "count",
          "points": [
            { "date": "2026-04-13", "value": 18, "unit": "count" }
          ]
        },
        {
          "key": "delayed_test_requirements",
          "label": "延期提测需求数",
          "unit": "count",
          "points": [
            { "date": "2026-04-13", "value": 2, "unit": "count" }
          ]
        },
        {
          "key": "delay_test_rate_okr",
          "label": "延期提测率",
          "unit": "%",
          "points": [
            { "date": "2026-04-13", "value": 11.1, "unit": "%" }
          ]
        }
      ]
    }
  ]
}
```

输出文件：

```text
joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
index.html
joyclaw-daily-inspection-orchestrator-skill/out/daily-inspection-summary.md
```

模板已经内置折线图渲染逻辑，不需要外部图表库。JoyClaw 不要改模板结构，只替换 JSON 数据。

## 中文巡检总结模板

每次完整巡检后，除 HTML 外还要生成可直接复制发送的中文 Markdown 巡检总结。

模板文件：

```text
joyclaw-daily-inspection-orchestrator-skill/assets/inspection-summary-template.md
```

填充脚本：

```text
joyclaw-daily-inspection-orchestrator-skill/scripts/render_inspection_summary.py
```

默认读取：

```text
joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
```

默认输出：

```text
joyclaw-daily-inspection-orchestrator-skill/out/daily-inspection-summary.md
```

总编排 `aggregate_report.py` 已经在写完总 JSON 和 HTML 后自动调用该脚本的填充逻辑。只想基于已有总 JSON 重新生成中文总结时，从项目根目录运行：

```bash
/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python joyclaw-daily-inspection-orchestrator-skill/scripts/render_inspection_summary.py
```

中文总结必须遵循：

- 模板文字使用中文。
- 所有指标值只从 `weekly-inspection-summary.json` 读取。
- 延期提测需求数、延期上线需求数只取当天 `repair_inspections` 中 **收银台&内单交易域** 的筛选延期数，不取 OKR C3 汇总里的延期需求数，也不取本周折线累计值。
- 巡检指标表要覆盖 OKR、AI、持续交付和延期修复相关指标。

## 总汇总

JoyClaw 确认延期提测率、延期上线率、技术改造工时占比、双周交付率、AI 巡检、持续交付的当天 JSON 已生成后，从项目根目录运行：

```bash
/Users/gaojingqi.5/miniconda3/envs/xunjian/bin/python joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py
```

默认输出：

```text
joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
index.html
joyclaw-daily-inspection-orchestrator-skill/out/daily-inspection-summary.md
```

脚本不接受自定义日期范围；本报告只展示当前自然周，也就是本周一到今天。

即使 `out/history/` 里存在上周、前周或更早的每日 JSON，JoyClaw 和聚合脚本都必须过滤掉，不得放入 HTML 折线图。

## AI 结果集成

AI 巡检只展示目标数据日结果，不画本周趋势。

总编排优先读取目标数据日源 JSON：

```text
AI-inspection/out/non_deep_users_YYYY-MM-DD.json
```

如果源 JSON 缺失，但已存在人名结果 JSON，可以兜底读取：

```text
AI-inspection/out/non_deep_user_names_YYYY-MM-DD.json
```

并筛选：

```text
是否深度用户 = 否
```

统一报告 JSON 中增加：

```json
{
  "ai_inspection": {
    "date": "2026-04-18",
    "indicator_type": "ai_non_deep_users",
    "indicator_name": "AI深度用户占比-软开测试岗",
    "status": "success",
    "source_json": "../../AI-inspection/out/non_deep_users_2026-04-18.json",
    "output_json": "",
    "count": 2,
    "names": ["蔡永乐", "常姜洲"],
    "users": [
      {
        "erp": "caiyongle",
        "name": "蔡永乐",
        "ai_code_local_submit_rate": 0.0,
        "is_deep_user": "否"
      }
    ]
  }
}
```

HTML 模板会把 `ai_inspection.users` 渲染为简约名单卡片，并展示人数。

## 持续交付结果集成

持续交付只展示当天结果，不画趋势。

持续交付脚本会先生成当天 JSON，JoyClaw 只需要校验字段并运行总编排。不要让总报告直接读截图，也不要只在对话中给出数值。

JoyClaw 读取：

```text
ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json
```

统一报告 JSON 中增加：

```json
{
  "continuous_delivery": {
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
      "query_screenshot": "assets/screenshots/continuous_delivery.png",
      "json": "../../ContinuousDelivery-inspection/out/continuous_delivery_2026-04-18.json"
    }
  }
}
```

HTML 模板会展示三项指标值，并贴当天三卡片截图。

如果当天持续交付 JSON 缺失，JoyClaw 必须回到 `ContinuousDelivery-inspection/SKILL.md` 的规则，先重新执行持续交付脚本生成当天 JSON，再重新生成总 HTML。

## 巡检完成输出模板

JoyClaw 跑完整体巡检并生成 `weekly-inspection-summary.json`、`index.html`、`daily-inspection-summary.md` 后，最终回复必须按下面模板输出。该模板只展示 **收银台&内单交易域** 的巡检总结和核心指标；最终回复中的部门、团队空间、域名称展示统一使用 **收银台&内单交易域**，即使 JSON 内部字段仍是原始部门名。

模板中的所有数值都必须从 `joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json` 读取，不要从截图、HTML 页面肉眼结果或手工记忆补数。缺失值统一写 `-`，缺失模块写清楚 `missing/partial/failed` 状态。

延期提测需求数、延期上线需求数必须取修复巡检中按 `团队空间 = 支付生态研发部` 筛出的数量，并以 **收银台&内单交易域** 名义展示；不要取 OKR C3 汇总里的 `支付方案研发部` 延期需求数。

模板中的报告地址必须从 `inspection-config.json` 的 `common.online_report_url` 读取。

```markdown
# 收银台&内单交易域巡检总结

巡检日期：{inspection_date}
数据周期：{time_range.start_date} 至 {time_range.end_date}
总状态：{status}
报告地址：{common.online_report_url}

## 核心指标

| 指标 | 最新值 | 最新日期 | 状态 |
| --- | ---: | --- | --- |
| 延期提测需求数 | {delayed_test.summary.筛选延期提测数} | {delayed_test.summary.巡检日期} | {delayed_test.summary.巡检状态} |
| 延期提测率 | {delay_test_rate.delay_test_rate_okr.latest}% | {delay_test_rate.latest_date} | {delay_test_rate.status} |
| 延期上线需求数 | {delayed_online.summary.筛选延期上线数} | {delayed_online.summary.巡检日期} | {delayed_online.summary.巡检状态} |
| 延期上线率 | {delay_online_rate.delay_online_rate.latest}% | {delay_online_rate.latest_date} | {delay_online_rate.status} |
| 技术改造工时占比 | {technical_refactor_working_hours.technical_refactor_working_hours_rate.latest}% | {technical_refactor_working_hours.latest_date} | {technical_refactor_working_hours.status} |
| 双周交付率 | {bi_weekly_delivery_rate.biweekly_delivery_rate.latest}% | {bi_weekly_delivery_rate.latest_date} | {bi_weekly_delivery_rate.status} |
| 持续交付上线需求占比 | {continuous_delivery.metrics.continuous_delivery_team_space_online_requirement_rate}% | {continuous_delivery.date} | {continuous_delivery.status} |
| AI 非深度用户数 | {ai_inspection.count} | {ai_inspection.date} | {ai_inspection.status} |

## 延期修复巡检

| 修复项 | 是否触发 | 巡检状态 | 筛选数 | 已修复数 | 失败数 |
| --- | --- | --- | ---: | ---: | ---: |
| 延期提测修复 | {delayed_test.trigger.triggered} | {delayed_test.summary.巡检状态} | {delayed_test.summary.筛选延期提测数} | {delayed_test.summary.已修复数} | {delayed_test.summary.失败数} |
| 延期上线修复 | {delayed_online.trigger.triggered} | {delayed_online.summary.巡检状态} | {delayed_online.summary.筛选延期上线数} | {delayed_online.summary.已修复数} | {delayed_online.summary.失败数} |

## 需关注

- {如果任一 OKR 指标缺失、AI/持续交付缺失、或修复巡检不是“通过/未触发”，这里列出原因。}
- {如果没有异常，写：暂无需关注项。}

## 产物

- HTML：index.html
- 在线报告：{common.online_report_url}
- 总 JSON：joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
- 巡检总结：joyclaw-daily-inspection-orchestrator-skill/out/daily-inspection-summary.md
```

输出规则：

- 只输出上面模板中的五段：标题与基础信息、核心指标、延期修复巡检、需关注、产物。
- 不粘贴原始 JSON，不展示截图路径明细，不展示失败/缺失字段空表。
- 表格中的百分比值只在最终展示时加 `%`，JSON 内部仍保持数字。
- `是否触发` 展示为 `是` 或 `否`，不要展示 `true` / `false`。
- `需关注` 必须放在显眼位置；有异常时逐条写清楚模块、状态和原因。
- 如果生成 HTML 时使用了 `--skip-repair`，并且延期修复被触发，`需关注` 中必须写明“本次跳过真实修复脚本，仅展示已有修复 JSON”。

## 成功标准

- OKR 4 个单项 skill 均已执行，或失败项有明确错误截图与错误信息。
- AI 巡检已执行，并且总编排已从当天 JSON 派生或兜底读取非深度用户名单。
- 持续交付巡检已执行，并且当天三指标 JSON 已生成。
- 延期提测率、延期上线率、技术改造工时占比、双周交付率都存在本周 `out/history/*.json`。
- 总 JSON 包含 4 个指标的本周历史序列。
- 如果当天延期提测或延期上线需求数大于 0，总 JSON 包含对应 `repair_inspections`，HTML 展示修复明细。
- 总 JSON 包含 `ai_inspection`。
- 总 JSON 包含 `continuous_delivery`。
- HTML 报告可以直接打开查看；最终 HTML 通过报告内部相对路径展示截图，上传 Web 时需要同时上传 `assets/screenshots/` 目录，且 HTML 中不得出现 base64 截图载荷、本机绝对截图路径或 `data:image/png;base64,...`。

## 清理规则

不要在生成总报告前删除历史 JSON。

如果用户要求周五清理本周巡检 JSON，只能在确认以下文件已生成后清理：

```text
joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
index.html
```
