---
name: ground-lite
description: 无人机仓库巡检地面站技能。支持任务发布、盘点判定、绑定维护、数据库查看、RFID/二维码查询。禁止任务启动与解锁起飞。用 scripts/gl.py 一键执行，响应最快。
---

# ground-lite 巡检地面站技能

## 权限边界（必须遵守）

### AI 可用
- **任务发布**：创建/覆盖任务（编号、名称、无人机、货架顺序）
- **盘点判定**：正确/放错/漏扫/多出；绑定写入/删除/清空
- **数据库查看**：表列表、行数据、CSV 导出（只读优先）
- **查询**：任务、无人机、货架、RFID、二维码、系统健康
- **二维码检测开关**、RFID 状态/记录查询

### AI 禁止（只允许人工在管理页操作）
- 任务 **start**（启动任务 / START_MISSION）
- **起飞、解锁、arm、unlock、takeoff** 等让无人机起飞的指令
- 若用户要求上述操作：明确拒绝并说明需人工执行

`gl.py` 已对 `start/takeoff/arm/unlock` 硬拦截。

## 一键脚本

```bash
G="/home/jetson/openclaw-workspace/skills/ground-lite/scripts/gl.py"

# 查询
python3 $G overview
python3 $G tasks 5
python3 $G task TASK-166
python3 $G task-qr TASK-166
python3 $G task-rfid TASK-166
python3 $G drones
python3 $G shelves
python3 $G bindings
python3 $G qr 20
python3 $G rfid 20
python3 $G rfid-status
python3 $G health
python3 $G search 关键词

# 任务发布（可用）
python3 $G publish-task TASK-201 巡检任务 1 01-01,02-01,02-02

# 盘点判定与绑定（可用）
python3 $G inventory
python3 $G bind EPC-001 SKU-001 01-01
python3 $G unbind 3
python3 $G clear-bindings
python3 $G qr-control on
python3 $G qr-control off

# 数据库查看（可用）
python3 $G db tables
python3 $G db rows inspection_tasks 20
python3 $G db export inventory_bindings

# 禁止
python3 $G start TASK-xxx        # ❌ 拒绝
python3 $G start-task TASK-xxx   # ❌ 拒绝
```

## 任务发布参数

`POST /api/tasks`：
```json
{"task_code":"TASK-201","name":"巡检任务","drone_id":1,"shelf_ids":["01-01","02-01"]}
```

## 绑定参数

`POST /api/inventory-bindings`：
```json
{"rfid":"EPC-001","sku":"SKU-001","shelf_code":"01-01"}
```

## 库表

inspection_tasks / inspection_task_shelves / drones / shelves /
inventory_bindings / qr_records / rfid_scan_records / rfid_scan_sessions /
drone_commands / drone_task_context

## HTTP 只读备查

```bash
BASE=http://127.0.0.1:8002
curl -sS $BASE/api/health
curl -sS $BASE/api/tasks
curl -sS $BASE/api/db/tables
```

**不要**调用 `POST /api/tasks/*/start`。`POST /api/tasks/*/stop` 仅在用户明确要求停止任务时考虑。

## 汇报格式

1. 一句话结论
2. 关键数据
3. 盘点：正确 / 放错 / 漏扫 / 多出
4. 涉及起飞启动时提示人工操作
