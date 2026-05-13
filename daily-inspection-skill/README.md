# JoyClaw 每日巡检项目帮助文档

## 1. 项目简介

这是一个给 JoyClaw 使用的每日巡检项目，目标是把 **OKR 巡检、延期修复巡检、AI 巡检、持续交付巡检** 统一收集起来，最终生成一份可查看的周报 HTML。

当前固定巡检部门：

- `支付方案研发部`

当前项目包含 4 类巡检内容：

1. **OKR 巡检**
   - 延期提测率
   - 延期上线率
   - 技术改造工时占比
   - 双周交付率
2. **延期修复巡检**
   - 延期提测需求修复
   - 延期上线需求修复
3. **AI 巡检**
   - 从目标数据日 AI 巡检结果里找出“是否深度用户 = 否”的人员名单
4. **持续交付巡检**
   - 团队空间开发测试上线需求数
   - 团队空间_持需交付_开发测试上线需求数
   - 持续交付_团队空间上线需求占比


## 2. 根目录结构

项目根目录主要结构如下：

```text
daily-inspection-skill/
├── SKILL.md
├── inspection-config.json
├── inspection_config.py
├── OKR-inspection/
│   ├── delay-test-rate-skill/
│   ├── delay-online-rate-skill/
│   ├── technical-refactor-working-hours-skill/
│   └── bi-weekly-delivery-rate-skill/
├── AI-inspection/
├── ContinuousDelivery-inspection/
├── reschedule-delayed-test/
├── repair-delayed-launch/
└── joyclaw-daily-inspection-orchestrator-skill/
```

各目录职责：

- `SKILL.md`
  - 项目总入口 skill
- `inspection-config.json`
  - 巡检网址、关注卡片、关注指标、部门/团队、修复触发字段和在线报告地址的统一配置
- `inspection_config.py`
  - 各脚本读取统一配置的公共入口
- `OKR-inspection/`
  - 4 个 OKR 巡检 skill
- `AI-inspection/`
  - AI 深度用户占比巡检
- `ContinuousDelivery-inspection/`
  - 持续交付三卡片巡检
- `reschedule-delayed-test/`
  - 延期提测需求修复脚本
- `repair-delayed-launch/`
  - 延期上线需求修复脚本
- `joyclaw-daily-inspection-orchestrator-skill/`
  - 总编排
  - 汇总 JSON
  - HTML 模板
  - 最终周报 HTML


## 3. 当前巡检职责划分

### 3.1 页面自动化脚本做什么

大多数 `scripts/run_skill.py` 负责：

- 打开页面
- 设置筛选项
- 点击查询
- 保存截图或下载源文件

其中：

- 延期提测率、延期上线率、技术改造工时占比
  - 会在查询后直接从目标卡片表格第一行提取当天值，并写入每日 JSON
- 双周交付率
  - 查询后 hover 图表 canvas，从 tooltip 提取双周交付率，并写入每日 JSON
- AI 巡检
  - 下载 Excel 后直接生成目标数据日源 JSON
- 持续交付
  - 会在查询后直接从三个指标卡片元素提取当天值，并写入当天 JSON


### 3.2 JoyClaw 做什么

JoyClaw 主要负责：

- 读取当天 JSON 和本周历史 JSON
- 根据 OKR 延期需求数触发对应修复脚本
- 生成本周趋势
- 把结果汇总进统一 HTML


### 3.3 双周交付率当前口径

双周交付率当前和前面三个 OKR skill 不同：

- 脚本查询后会 hover ECharts canvas
- 脚本从 tooltip 里读取 `双周交付率：xx%`
- 脚本生成当天 JSON；JoyClaw 只负责读取历史 JSON 生成趋势


## 4. 巡检顺序

统一执行顺序必须是：

1. 先巡检 **OKR**
2. 再巡检 **AI**
3. 再巡检 **持续交付**
4. 最后跑 **总编排**

OKR 内部顺序：

1. `delay-test-rate-skill`
2. `delay-online-rate-skill`
3. `technical-refactor-working-hours-skill`
4. `bi-weekly-delivery-rate-skill`


## 5. 快速开始

### 5.1 运行环境

当前项目默认使用当前 Python。需要指定本机虚拟环境时，设置 `XUNJIAN_PYTHON`：

```bash
export XUNJIAN_PYTHON="/path/to/xunjian/bin/python"
```

执行前建议确认：

- 本机能正常打开相关 JD 内网页面
- Playwright 浏览器环境可用
- 当前账号已登录需要的系统


### 5.2 单项执行命令

#### OKR 四项

分别进入各自目录执行：

```bash
"${XUNJIAN_PYTHON:-python3}" scripts/run_skill.py
```

适用目录：

- `OKR-inspection/delay-test-rate-skill`
- `OKR-inspection/delay-online-rate-skill`
- `OKR-inspection/technical-refactor-working-hours-skill`
- `OKR-inspection/bi-weekly-delivery-rate-skill`

#### AI 巡检

在 `AI-inspection` 目录执行：

```bash
"${XUNJIAN_PYTHON:-python3}" scripts/run_skill.py
```

#### 持续交付巡检

在 `ContinuousDelivery-inspection` 目录执行：

```bash
"${XUNJIAN_PYTHON:-python3}" scripts/run_skill.py
```

#### 总编排

在项目根目录执行：

```bash
"${XUNJIAN_PYTHON:-python3}" joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py
```


## 6. 标准执行链路

### 第一步：跑 OKR 四项

#### 延期提测率

脚本会从目标卡片表格第一行直接提取当天数据，并生成：

```text
OKR-inspection/delay-test-rate-skill/out/history/YYYY-MM-DD.json
```

JoyClaw 只读取这份当天 JSON 和本周 `out/history/` 中已有 JSON，不从截图补数据。

#### 延期上线率

脚本会从目标卡片表格第一行直接提取当天数据，并生成：

```text
OKR-inspection/delay-online-rate-skill/out/history/YYYY-MM-DD.json
```

JoyClaw 只读取这份当天 JSON 和本周 `out/history/` 中已有 JSON，不从截图补数据。

如果当天 OKR JSON 中 `delayed_test_requirements > 0`，总编排会执行 `reschedule-delayed-test/main.py` 并读取 `reschedule-delayed-test/history/YYYY-MM-DD.json`。如果 `delayed_online_requirements > 0`，总编排会执行 `repair-delayed-launch/main.py` 并读取 `repair-delayed-launch/history/YYYY-MM-DD.json`。本地只想重新生成 HTML 时，可以给总编排加 `--skip-repair`，只展示已有修复 JSON。

#### 技术改造工时占比

脚本会从目标卡片表格第一行直接提取当天数据，并生成：

```text
OKR-inspection/technical-refactor-working-hours-skill/out/history/YYYY-MM-DD.json
```

JoyClaw 只读取这份当天 JSON 和本周 `out/history/` 中已有 JSON，不从截图补数据。

#### 双周交付率

脚本查询后保存截图，并 hover 图表 canvas 读取 tooltip 中的“双周交付率”，直接生成当天 JSON：

```text
OKR-inspection/bi-weekly-delivery-rate-skill/out/history/YYYY-MM-DD.json
```

说明：

- 当前只关注一个指标：`biweekly_delivery_rate`
- 不再输出完成需求数、总需求数、双周内交付需求数
- 如果当天 JSON 缺失，优先重跑双周交付率脚本，不再从截图估算数值


### 第二步：跑 AI 巡检

AI 脚本会下载 Excel，并生成目标数据日源 JSON：

```text
AI-inspection/out/non_deep_users_YYYY-MM-DD.json
```

然后总编排从对应日期的源 JSON 派生 `ai_inspection` 名单；周一巡检时 AI 日期取上周五，周二至周五取前一工作日，周末兜底取周五。如果已存在 `AI-inspection/out/non_deep_user_names_YYYY-MM-DD.json`，可作为兜底读取。


### 第三步：跑持续交付巡检

持续交付脚本会生成：

```text
ContinuousDelivery-inspection/out/three_cards.png
ContinuousDelivery-inspection/out/continuous_delivery_YYYY-MM-DD.json
```


### 第四步：跑总编排

总编排会读取前面产出的 JSON，并生成：

```text
joyclaw-daily-inspection-orchestrator-skill/out/weekly-inspection-summary.json
index.html
joyclaw-daily-inspection-orchestrator-skill/out/daily-inspection-summary.md
```

最终 HTML 会内置巡检数据，但截图仍通过 `assets/screenshots/...` 相对路径显示。Markdown 巡检总结由中文模板和总 JSON 填充生成。


## 7. 各模块输入输出一览

| 模块 | 输入 | 输出 |
| --- | --- | --- |
| 延期提测率 | 当天 JSON | `out/history/YYYY-MM-DD.json` |
| 延期上线率 | 当天 JSON | `out/history/YYYY-MM-DD.json` |
| 技术改造工时占比 | 当天 JSON | `out/history/YYYY-MM-DD.json` |
| 双周交付率 | 图表 tooltip | `out/history/YYYY-MM-DD.json` |
| AI 巡检 | 目标数据日源 JSON | `out/non_deep_users_YYYY-MM-DD.json`；周一取上周五，周二至周五取前一工作日，已有 `out/non_deep_user_names_YYYY-MM-DD.json` 时可兜底 |
| 持续交付 | 当天 JSON | `out/continuous_delivery_YYYY-MM-DD.json` |
| 总编排 | 各模块 JSON | `weekly-inspection-summary.json`、根目录 `index.html`、`daily-inspection-summary.md` |


## 8. 当前报表规则

### 8.1 时间范围

最终 HTML 只展示：

- **本周周一到今天**

不会展示前一周或更早的自然周数据。

规则：

- 本周起点：本周一
- 本周终点：今天
- 不补不存在的日期
- 缺失日期不画点


### 8.2 HTML 模板位置

模板文件：

[weekly-line-report-template.html](/Users/gaojingqi.5/Desktop/daily-inspection-skill/joyclaw-daily-inspection-orchestrator-skill/assets/weekly-line-report-template.html)

最终产物：

[index.html](/Users/gaojingqi.5/Desktop/daily-inspection-skill/index.html)


### 8.3 折线图规则

- 延期提测需求：1 条线，读取 `reschedule-delayed-test/history/*.json` 的 `results.length`，展示收银台&内单交易域下筛出的延期提测需求数
- 延期上线需求：1 条线，读取 `repair-delayed-launch/history/*.json` 的 `results.length`，展示收银台&内单交易域下筛出的延期上线需求数
- 技术改造工时占比：1 条线
  - `technical_refactor_working_hours_rate`
- 双周交付率：1 条线
  - `biweekly_delivery_rate`

支持点击图例或折线高亮查看。


### 8.4 截图处理规则

最终 HTML 中的截图已经做过处理：

- 不暴露本机绝对路径
- 不保留原始文件地址
- 不使用 `data:image`
- 不内嵌 base64 截图载荷
- 通过 `assets/screenshots/...` 相对路径显示

所以最终上传展示时，需要把最终 HTML 和同级 `assets/screenshots/` 目录一起上传。


### 8.5 中文巡检总结模板

除了 HTML，项目还提供一份可直接发送的中文 Markdown 巡检总结。

模板文件：

[inspection-summary-template.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/joyclaw-daily-inspection-orchestrator-skill/assets/inspection-summary-template.md)

填充脚本：

[render_inspection_summary.py](/Users/gaojingqi.5/Desktop/daily-inspection-skill/joyclaw-daily-inspection-orchestrator-skill/scripts/render_inspection_summary.py)

默认输出：

[daily-inspection-summary.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/joyclaw-daily-inspection-orchestrator-skill/out/daily-inspection-summary.md)

单独重新填充：

```bash
"${XUNJIAN_PYTHON:-python3}" joyclaw-daily-inspection-orchestrator-skill/scripts/render_inspection_summary.py
```

总编排 `aggregate_report.py` 会在生成 `weekly-inspection-summary.json` 和 `index.html` 后自动生成这份 Markdown。

注意：Markdown 中的 `延期提测需求数`、`延期上线需求数` 只取当天修复巡检里 **收银台&内单交易域** 的筛选延期数，不取 OKR C3 汇总延期需求数，也不取本周折线累计值。


## 9. 最新日期规则

最终 HTML 卡片顶部的“最新日期”使用：

- 报告 JSON 根字段 `inspection_date`

也就是：

- **当天巡检日期**

不是折线图最后一个数据点的日期。


## 10. 关键文件位置

### 根编排

- [SKILL.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/SKILL.md)
- [aggregate_report.py](/Users/gaojingqi.5/Desktop/daily-inspection-skill/joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py)

### OKR

- [delay-test-rate-skill](/Users/gaojingqi.5/Desktop/daily-inspection-skill/OKR-inspection/delay-test-rate-skill)
- [delay-online-rate-skill](/Users/gaojingqi.5/Desktop/daily-inspection-skill/OKR-inspection/delay-online-rate-skill)
- [technical-refactor-working-hours-skill](/Users/gaojingqi.5/Desktop/daily-inspection-skill/OKR-inspection/technical-refactor-working-hours-skill)
- [bi-weekly-delivery-rate-skill](/Users/gaojingqi.5/Desktop/daily-inspection-skill/OKR-inspection/bi-weekly-delivery-rate-skill)

### AI

- [AI-inspection/SKILL.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/AI-inspection/SKILL.md)

### 持续交付

- [ContinuousDelivery-inspection/SKILL.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/ContinuousDelivery-inspection/SKILL.md)


## 11. 常见问题

### 11.1 为什么有截图但没有当天 JSON

先看是哪类模块：

- 延期提测率 / 延期上线率 / 技术改造工时占比
  - 这三项会由脚本直接生成当天 JSON
- 双周交付率
  - 这项由脚本 hover 图表 canvas，读取 tooltip 后生成当天 JSON
- 持续交付
  - 这项也由脚本直接生成当天 JSON，并保留 `three_cards.png`
- AI
  - 先有当天源 JSON，总编排再派生名单；已有单独人名 JSON 时可兜底


### 11.2 双周交付率提取失败怎么办

优先检查：

- 页面是否成功查询
- `out/03_after_query.png` 是否生成
- 鼠标 hover 图表 canvas 后是否出现包含“双周交付率”的 tooltip
- 脚本是否已经生成 `out/history/YYYY-MM-DD.json`

双周交付率现在走 tooltip 提取路线，所以重点看目标图表是否完整加载、canvas 是否可 hover、tooltip 文案是否包含“双周交付率：xx%”。


### 11.3 为什么 HTML 上传后变成下载

这通常不是 HTML 内容问题，而是文件托管平台把它当附件下载了。

要想在线看，需要托管平台返回类似：

- `Content-Type: text/html`
- `Content-Disposition: inline`

如果平台给的是 `/download/...` 这种接口，浏览器大概率会直接下载。


### 11.4 为什么线上看不到图片

当前 HTML 已经避免使用本机绝对路径，但如果目标平台限制：

- `blob:` 图片
- 内联脚本

那页面里的截图仍可能加载失败。这时需要换支持静态 HTML 预览的平台。


## 12. 推荐交接阅读顺序

如果是第一次接手这个项目，建议按这个顺序看：

1. 本文档
2. [SKILL.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/SKILL.md)
3. 各模块自己的 `SKILL.md`
4. `joyclaw-daily-inspection-orchestrator-skill/scripts/aggregate_report.py`
5. 最终 HTML 模板


## 13. 当前项目默认事实

- 总编排主 skill 在根目录 [SKILL.md](/Users/gaojingqi.5/Desktop/daily-inspection-skill/SKILL.md)
- 总编排实现和模板仍在 `joyclaw-daily-inspection-orchestrator-skill/`，展示页输出到根目录 `index.html`
- HTML 只展示本周数据
- HTML 会集成 OKR、延期修复、AI、持续交付四部分内容
- 双周交付率只关注 `biweekly_delivery_rate`
- HTML 截图不允许暴露原始本地路径
