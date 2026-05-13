# 周四改周五需求修正工具帮助文档

## 这个工具做什么

本目录下的脚本用于处理 JD 星云看板中第二个 `cards-board__group` 里的需求卡片。

核心流程是：

1. 打开 `JD_Cashier` 看板列表页。
2. 提取每个迭代的 `data-item`，拼成 `sprintId` 页面。
3. 读取每个迭代页面里第二组需求卡片。
4. 找出 `计划提测日期` 或 `计划上线日期` 等于本周四的需求。
5. 用 `sprintId + cardId` 直接打开需求详情页。
6. 将命中的日期改成本周五。
7. 写入 JSON 结果，并自动刷新 HTML 报告。

示例详情地址：

```text
http://xingyun.jd.com/teamspace/scrum/JD_Cashier/allWorkItems?sprintId=327085&cardId=6136706
```

## 文件说明

### `open_jd_cashier.py`

主脚本。负责打开页面、提取需求、修改日期、写入 JSON，并调用报告生成脚本。

运行命令：

```bash
"${XUNJIAN_PYTHON:-python3}" thursday-to-friday-adjustment/open_jd_cashier.py
```

### `generate_modification_report.py`

报告生成脚本。读取 JSON 文件并生成 HTML 报告。

单独刷新报告：

```bash
"${XUNJIAN_PYTHON:-python3}" thursday-to-friday-adjustment/generate_modification_report.py
```

### `index.html`

本地 HTML 报告页。展示修改结果。

浏览器打开地址：

```text
file:///Users/gaojingqi.5/Desktop/thursday-to-friday-adjustment/index.html
```

注意：现在报告文件名是 `index.html`。如果浏览器还停在旧地址：

```text
file:///Users/gaojingqi.5/Desktop/thursday-to-friday-adjustment/modification_report.html
```

需要手动切换到 `index.html`。

## 输出 JSON

### `sprint_data_items.json`

完整提取结果。包含每个迭代、每张需求卡片、卡片字段和详情处理动作。

常见字段：

```json
{
  "title": "【收银台S84】",
  "data_item": "327085",
  "detail_url": "...?sprintId=327085",
  "second_group_items": []
}
```

### `thursday_demands.json`

所有命中本周四的需求合集。

命中条件：

```text
计划提测日期 == 本周四
或
计划上线日期 == 本周四
```

### `thursday_submit_test_demands.json`

只包含 `计划提测日期 == 本周四` 的需求。

### `thursday_online_demands.json`

只包含 `计划上线日期 == 本周四` 的需求。

### `thursday_to_friday_modified.json`

真实修改结果。

主要字段：

```json
{
  "source_date": "2026-05-07",
  "target_date": "2026-05-08",
  "count": 14,
  "modified_items": [],
  "failed_items": []
}
```

`modified_items` 中每条记录会包含：

```json
{
  "demand_name": "需求名称",
  "owner": "负责人",
  "sprint_title": "迭代名称",
  "sprint_data_item": "sprintId",
  "item_id": "cardId",
  "field_label": "计划提测日期 或 计划上线日期",
  "old_value": "2026-05-07",
  "new_value": "2026-05-08",
  "page_current_value": "2026-05-08",
  "confirm_clicked": true,
  "detail_url": "详情页地址",
  "modified_at": "修改时间"
}
```

`failed_items` 会记录未修改成功的需求和原因。

## HTML 报告内容

`index.html` 会展示：

- 修改提测
- 修改上线
- 失败记录
- 本周四提测清单
- 本周四上线清单
- 成功数、失败数、源日期、目标日期等摘要指标

报告每次运行 `open_jd_cashier.py` 后会自动刷新。

也可以单独运行 `generate_modification_report.py` 刷新。

## 当前关键逻辑

### 为什么用 `cardId`

之前通过点击卡片打开详情，容易读到上一个详情面板的数据。

现在改为直接拼 URL：

```text
?sprintId=xxx&cardId=yyy
```

这样每个需求详情页独立打开，准确率更高。

### 什么需求会被跳过

以下情况会跳过：

- 需求名称已加载，但卡片里没有 `计划提测日期` 和 `计划上线日期`。
- 卡片日期不是本周四。
- 详情页读到的日期和卡片命中的本周四不一致。
- 详情页找不到对应日期字段。

跳过或失败原因会写入 JSON。

## 常见问题

### 1. HTML 没更新

确认报告文件是：

```text
index.html
```

再单独运行：

```bash
"${XUNJIAN_PYTHON:-python3}" thursday-to-friday-adjustment/generate_modification_report.py
```

### 2. 浏览器打开的是旧页面

检查地址栏是不是旧文件名：

```text
modification_report.html
```

如果是，改成：

```text
index.html
```

### 3. 修改数量为 0

检查：

- `thursday_demands.json` 里是否有命中本周四的需求。
- `thursday_to_friday_modified.json` 的 `failed_items` 是否有失败原因。
- 页面是否已经登录。
- 详情页里的日期是否已经被改成周五。

### 4. 页面需要登录

脚本打开浏览器后，如果登录态失效，需要先登录星云系统。

登录完成后重新运行脚本。

## 推荐运行顺序

正常只需要运行主脚本：

```bash
"${XUNJIAN_PYTHON:-python3}" thursday-to-friday-adjustment/open_jd_cashier.py
```

如果只是想刷新 HTML：

```bash
"${XUNJIAN_PYTHON:-python3}" thursday-to-friday-adjustment/generate_modification_report.py
```

## 维护提醒

如果以后修改 HTML 文件名，需要同步修改：

```python
REPORT_HTML = BASE_DIR / "index.html"
```

位置：

```text
generate_modification_report.py
```
