---
name: ground-lite
description: 无人机仓库巡检地面站技能。任务发布、盘点、绑定、库表、查询可直接执行；start/起飞/解锁等敏感指令须操作员在对话提供密钥并通过 --key 校验。
---

# ground-lite 巡检地面站技能

> **权限速记**
> - **直接执行**：发布任务、盘点、绑定、库表、查询、stop
> - **敏感指令**（start / takeoff / arm / unlock）：必须操作员在对话里给出密钥，命令加 `--key <密钥>`
> - 密钥**只来自操作员对话**，不要向别人索要，不要写入日志/仓库

## 敏感指令用法

操作员消息中应包含密钥，例如：
`密钥 jetson，启动 TASK-202`

执行：
```bash
python3 $G start TASK-202 --key jetson
```

密钥错误或未提供 → 拒绝执行并说明。校验通过才可 `start`（下发航线/启动任务）。

## 一键脚本

```bash
G="/home/jetson/openclaw-workspace/skills/ground-lite/scripts/gl.py"

python3 $G overview
python3 $G tasks 5
python3 $G task TASK-166
python3 $G publish-task TASK-202 货架复核 1 01-01,02-01
python3 $G inventory
python3 $G bind EPC-001 SKU-001 01-01
python3 $G db tables
python3 $G db rows inspection_tasks 20
python3 $G start TASK-202 --key <对话中的密钥>
```

## 任务发布

```json
{"task_code":"TASK-202","name":"货架复核","drone_id":1,"shelf_ids":["01-01","02-01"]}
```

## 汇报

1. 结论 2. 关键数据 3. 盘点差异 4. 敏感操作注明「已用操作员密钥执行 / 密钥校验失败」
