# JoyClaw 自动巡检：延期提测率

## 适用范围

用于 JoyClaw 巡检“延期提测率”修复结果。巡检只读取本目录当天生成的 JSON，不直接操作浏览器、不重新修改需求。

本目录：

```text
/Users/gaojingqi.5/Desktop/daily-inspection-skill/reschedule-delayed-test 
```

当天 JSON 路径：

```text
history/YYYY-MM-DD.json
```

日期使用 Asia/Shanghai 当天日期。例如 2026-04-30 对应：

```text
history/2026-04-30.json
```

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
未生成当天延期提测率巡检 JSON，无法确认修复结果。
```

如果 JSON 为空或格式错误，巡检结果为：

```text
当天延期提测率巡检 JSON 为空或格式异常，无法确认修复结果。
```

## 提取优先级

以 `modified_items` 为主，因为它代表已经进入详情页并尝试修改过。

对每条记录按 `需求编码` 合并字段：

1. 从 `modified_items` 提取修复结果。
2. 从 `results` 补充 `团队空间`、`是否延期提测`、`研发负责人`、`修正后计划提测日期`、`跳转地址`。
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
  "是否延期提测": "",
  "研发负责人": "",
  "修改字段": "计划提测日期",
  "修改前": "",
  "修改后": "",
  "修正后计划提测日期": "",
  "页面当前值": "",
  "是否点击确认": false,
  "跳转地址": "",
  "modified_at": ""
}
```

字段说明：

- `修正后计划提测日期` 优先取同名字段；缺失时取 `修改后`。
- `跳转地址` 优先取 `跳转地址`；缺失时取 `页面URL`。
- `研发负责人` 优先取 `modified_items`；缺失时从 `results` 补。
- `是否点击确认` 允许为 `false`，因为当天日期不晚于期望日期时可能没有确认弹窗。

## 成功判定

一条需求视为修复成功，需要同时满足：

- `需求编码` 非空。
- `修改字段` 等于 `计划提测日期`。
- `修正后计划提测日期` 非空。
- `跳转地址` 非空。
- `研发负责人` 非空。
- `修改后` 等于 `修正后计划提测日期`，或 `修改后` 为空但 `修正后计划提测日期` 非空。

如果 `页面当前值` 非空，建议校验：

```text
页面当前值 == 修正后计划提测日期
```

不一致时标记为“需人工复核”。

## 失败判定

从 `modify_failed_items` 提取失败记录。每条失败记录至少输出：

```json
{
  "需求编码": "",
  "需求名称": "",
  "修改字段": "计划提测日期",
  "失败原因": "",
  "failed_at": ""
}
```

如果存在失败记录，巡检状态为“存在失败项”。

## 输出建议

JoyClaw 巡检输出建议包含：

```json
{
  "巡检项": "延期提测率",
  "巡检日期": "YYYY-MM-DD",
  "数据周期": "date_range",
  "部门": "department_c3",
  "团队空间": "team_space",
  "筛选延期提测数": 0,
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

- `筛选延期提测数`: `len(results)`
- `已点击数`: `clicked_count`，缺失时用 `len(clicked_items)`
- `已修复数`: `modified_count`，缺失时用 `len(modified_items)`
- `失败数`: `len(modify_failed_items)`

## 缺失字段检查

对 `modified_items` 中每条成功记录检查这些字段：

- `研发负责人`
- `修正后计划提测日期`
- `跳转地址`

缺任一字段时，加入 `缺失字段明细`，巡检状态设为“需人工复核”。

## 示例提取逻辑

伪代码：

```python
data = load_json("history/YYYY-MM-DD.json")

results_by_code = {item["需求编码"]: item for item in data.get("results", [])}
clicked_by_code = {item["需求编码"]: item for item in data.get("clicked_items", [])}

success = []
missing = []

for item in data.get("modified_items", []):
    code = item.get("需求编码", "")
    merged = {}
    merged.update(results_by_code.get(code, {}))
    merged.update(clicked_by_code.get(code, {}))
    merged.update(item)

    merged["修正后计划提测日期"] = (
        merged.get("修正后计划提测日期") or merged.get("修改后", "")
    )
    merged["跳转地址"] = merged.get("跳转地址") or merged.get("页面URL", "")

    required = ["研发负责人", "修正后计划提测日期", "跳转地址"]
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

## 注意事项

- 不要用巡检流程再次修改页面；巡检只解析 JSON。
- 当天没有运行修复脚本时，不要读取历史日期 JSON 冒充当天结果。
- 如果 `results` 为空但 `modified_items` 有数据，以 `modified_items` 为准输出修复明细。
- 如果 JSON 中已有 `跳转地址`，不要重新拼接 URL。
- 本脚本修复的是 `计划提测日期`，不要混用 `计划上线日期`。
