# JoyClaw 自动巡检：延期上线率

## 适用范围

用于 JoyClaw 巡检“延期上线率”修复结果。巡检只读取本目录当天生成的 JSON，不直接操作浏览器、不重新修改需求。

本目录：

```text
/Users/gaojingqi.5/Desktop/daily-inspection-skill/repair-delayed-launch
```

当天 JSON 路径：

```text
history/YYYY-MM-DD.json
```

日期使用 Asia/Shanghai 当天日期。例如 2026-04-30 对应：

```text
history/2026-04-30.json
```

## 当前脚本流程

这个目录的脚本用于修复“需求明细-延期上线”：

- `config.py`: 定义卡片、部门、团队空间和目标日期字段。当前目标为 `CARD_TITLE = "需求明细-延期上线"`，`DEPARTMENT_C3 = "支付方案研发部"`，`TEAM_SPACE_TARGET = "支付生态研发部"`，`TARGET_DATE_FIELD_LABEL = "计划上线日期"`。
- `main.py`: 打开 BI 页面，筛选“卡片完成日期”和“任务处理人部门C3”，抽取延期上线需求列表，写入当天 JSON。
- `table_ops.py`: 从表格提取 `需求编码`、`需求名称`、`团队空间`、`是否延期上线`，只保留 `是否延期上线 == "延期上线"` 且 `团队空间 == "支付生态研发部"` 的记录。
- `workflow.py`: 根据当天 JSON 的 `results` 逐条打开需求详情，修改 `计划上线日期`，并回写 `clicked_items`、`modified_items`、`modify_failed_items`。
- `detail_page.py`: 在需求详情页提取 `研发负责人`、`跳转地址`，把 `计划上线日期` 修改为当天日期。
- `common.py`: 负责 JSON 读取、合并和原子写入；重跑脚本时会保留历史点击和修改状态。

## 输入文件

JoyClaw 读取当天 JSON，要求 JSON 顶层可能包含：

- `date_range`
- `department_c3`
- `team_space`
- `results`
- `clicked_items`
- `modified_items`
- `modify_failed_items`
- `modified_count`
- `clicked_count`

如果当天 JSON 不存在，巡检结果为：

```text
未生成当天延期上线率巡检 JSON，无法确认修复结果。
```

如果 JSON 为空或格式错误，巡检结果为：

```text
当天延期上线率巡检 JSON 为空或格式异常，无法确认修复结果。
```

## 提取优先级

以 `modified_items` 为主，因为它代表已经进入详情页并尝试修改过。

对每条记录按 `需求编码` 合并字段：

1. 从 `modified_items` 提取修复结果。
2. 从 `results` 补充 `团队空间`、`是否延期上线`、`研发负责人`、`修正后计划上线日期`、`跳转地址`。
3. 从 `clicked_items` 补充 `跳转地址`。
4. 从 `modify_failed_items` 提取失败记录。

同一 `需求编码` 出现多次时，保留一条合并后的记录。

## 必提字段

每条成功修复记录应提取这些字段：

```json
{
  "需求编码": "",
  "需求名称": "",
  "团队空间": "",
  "是否延期上线": "",
  "研发负责人": "",
  "修改字段": "计划上线日期",
  "修改前": "",
  "修改后": "",
  "修正后计划上线日期": "",
  "页面当前值": "",
  "是否点击确认": false,
  "跳转地址": "",
  "modified_at": ""
}
```

字段说明：

- `修正后计划上线日期` 优先取同名字段；缺失时取 `修改后`。
- `跳转地址` 优先取 `跳转地址`；缺失时取 `页面URL`。
- `研发负责人` 优先取 `modified_items`；缺失时从 `results` 补。
- `是否点击确认` 允许为 `false`，因为当天日期不晚于期望上线日期时可能没有确认弹窗。

## 成功判定

一条需求视为修复成功，需要同时满足：

- `需求编码` 非空。
- `修改字段` 等于 `计划上线日期`。
- `修正后计划上线日期` 非空。
- `跳转地址` 非空。
- `研发负责人` 非空。
- `修改后` 等于 `修正后计划上线日期`，或 `修改后` 为空但 `修正后计划上线日期` 非空。

如果 `页面当前值` 非空，建议校验：

```text
页面当前值 == 修正后计划上线日期
```

不一致时标记为“需人工复核”。

## 失败判定

从 `modify_failed_items` 提取失败记录。每条失败记录至少输出：

```json
{
  "需求编码": "",
  "需求名称": "",
  "修改字段": "计划上线日期",
  "失败原因": "",
  "failed_at": ""
}
```

如果存在失败记录，巡检状态为“存在失败项”。

## 输出建议

JoyClaw 巡检输出建议包含：

```json
{
  "巡检项": "延期上线率",
  "巡检日期": "YYYY-MM-DD",
  "数据周期": "date_range",
  "部门": "department_c3",
  "团队空间": "team_space",
  "筛选延期上线数": 0,
  "已点击数": 0,
  "已修复数": 0,
  "失败数": 0,
  "巡检状态": "通过/存在失败项/无当天JSON/JSON异常/需人工复核",
  "成功明细": [],
  "失败明细": [],
  "缺失字段明细": []
}
```

计数规则：

- `筛选延期上线数`: `len(results)`
- `已点击数`: `clicked_count`，缺失时用 `len(clicked_items)`
- `已修复数`: `modified_count`，缺失时用 `len(modified_items)`
- `失败数`: `len(modify_failed_items)`

状态判定建议：

- 当天 JSON 不存在，输出 `无当天JSON`。
- 当天 JSON 为空或格式错误，输出 `JSON异常`。
- `results`、`modified_items`、`modify_failed_items` 都为空，输出 `通过`，并备注“当天无延期上线需求”。
- `modify_failed_items` 非空，输出 `存在失败项`。
- 任一成功记录缺少 `研发负责人`、`修正后计划上线日期`、`跳转地址`，输出 `需人工复核`。
- `页面当前值` 与 `修正后计划上线日期` 不一致，输出 `需人工复核`。
- `results` 非空且 `已修复数 < 筛选延期上线数`，同时无失败记录时，输出 `需人工复核`，表示存在筛出但未修复的需求。
- 其余情况输出 `通过`。

## 缺失字段检查

对 `modified_items` 中每条成功记录检查这些字段：

- `研发负责人`
- `修正后计划上线日期`
- `跳转地址`

缺任一字段时，加入 `缺失字段明细`，巡检状态设为“需人工复核”。

## 示例提取逻辑

伪代码：

```python
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo


base_dir = Path("/Users/gaojingqi.5/Desktop/daily-inspection-skill/repair-delayed-launch")
today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
json_path = base_dir / "history" / f"{today:%Y-%m-%d}.json"

data = json.loads(json_path.read_text(encoding="utf-8"))

results_by_code = {
    item.get("需求编码", ""): item
    for item in data.get("results", [])
    if item.get("需求编码")
}
clicked_by_code = {
    item.get("需求编码", ""): item
    for item in data.get("clicked_items", [])
    if item.get("需求编码")
}

success = []
missing = []

for item in data.get("modified_items", []):
    code = item.get("需求编码", "")
    merged = {}
    merged.update(results_by_code.get(code, {}))
    merged.update(clicked_by_code.get(code, {}))
    merged.update(item)

    merged["修正后计划上线日期"] = (
        merged.get("修正后计划上线日期") or merged.get("修改后", "")
    )
    merged["跳转地址"] = merged.get("跳转地址") or merged.get("页面URL", "")

    required = ["研发负责人", "修正后计划上线日期", "跳转地址"]
    absent = [field for field in required if not merged.get(field)]
    if absent:
        missing.append({
            "需求编码": code,
            "需求名称": merged.get("需求名称", ""),
            "缺失字段": absent,
        })

    success.append(merged)

failed = data.get("modify_failed_items", [])
```

## 2026-04-30 当前 JSON 示例

当前 `history/2026-04-30.json` 可提取到：

```json
{
  "巡检项": "延期上线率",
  "巡检日期": "2026-04-30",
  "数据周期": "2026-04-24 ~ 2026-04-30",
  "部门": "支付方案研发部",
  "团队空间": "支付生态研发部",
  "筛选延期上线数": 1,
  "已点击数": 1,
  "已修复数": 1,
  "失败数": 0,
  "巡检状态": "通过",
  "成功明细": [
    {
      "需求编码": "R2026031642817",
      "需求名称": "【JD支付】待支付订详-工具前置-白条二期",
      "研发负责人": "赵波",
      "修改字段": "计划上线日期",
      "修改前": "2026-04-29",
      "修改后": "2026-04-30",
      "修正后计划上线日期": "2026-04-30",
      "页面当前值": "2026-04-30",
      "是否点击确认": true,
      "跳转地址": "http://xingyun.jd.com/teamspace/scrum/JD_Cashier/workitems/product_demand?cardId=5994577&sprintId=321390",
      "modified_at": "2026-04-30 13:42:10"
    }
  ],
  "失败明细": [],
  "缺失字段明细": []
}
```

## 注意事项

- 不要用巡检流程再次修改页面；巡检只解析 JSON。
- 当天没有运行修复脚本时，不要读取历史日期 JSON 冒充当天结果。
- 如果 `results` 为空但 `modified_items` 有数据，以 `modified_items` 为准输出修复明细。
- 如果 JSON 中已有 `跳转地址`，不要重新拼接 URL。
- 本脚本修复的是 `计划上线日期`，不要混用 `计划提测日期`。
- `date_range` 由脚本按“上一个周五到当天”生成；如果当天是周五，开始日期取前一个周五。
