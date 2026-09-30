---
name: ground-lite
description: 无人机仓库巡检地面站 (ground-lite) 任务/盘点/数据库技能。用 scripts/gl.py 一键查询任务、无人机、货架、RFID/二维码、绑定与盘点差异，响应最快。禁止执行起飞/启停任务等飞行指令。当用户问巡检任务、盘点、货架、RFID、二维码、无人机状态时使用。
---

# ground-lite 巡检地面站技能

## 铁律（必须遵守）

1. **禁止执行飞行相关命令**，不要调用：
   - `POST /api/tasks/*/start`（启动任务/起飞）
   - `POST /api/tasks/*/stop`
   - `POST /api/drones/*/tasks/current/abort`
   - 任何起飞、降落、航线执行类接口
   - 若用户要求启停任务，只说明需在管理页人工操作，不要代执行。
2. **数据库/查询全部走本地脚本**，不要让模型自己拼一堆 curl 试错，这是提速关键。
3. 回答用中文，先结论后数据。

## 一键脚本（优先用这个）

路径：`scripts/gl.py`（相对本 skill 目录）。也可用绝对路径：
`/home/jetson/openclaw-workspace/skills/ground-lite/scripts/gl.py`

```bash
G="/home/jetson/openclaw-workspace/skills/ground-lite/scripts/gl.py"
python3 $G overview          # 总览：无人机+最近任务+货架+绑定数量
python3 $G tasks [N]         # 最近 N 个任务（默认 5）
python3 $G task TASK-166     # 单任务详情+货架顺序
python3 $G task-qr TASK-166  # 任务二维码记录
python3 $G task-rfid TASK-166 # 任务 RFID 记录
python3 $G drones            # 无人机状态
python3 $G shelves           # 货架
python3 $G bindings          # RFID↔SKU↔货架绑定
python3 $G qr [N]            # 最近二维码
python3 $G rfid [N]          # 最近 RFID
python3 $G inventory         # 盘点判定：多出/缺失/放错/正确
python3 $G search KEYWORD    # 任务/货架/绑定模糊搜索
python3 $G health            # 地面站健康
```

脚本直读 SQLite（`/data` 卷在宿主机映射后也可用 HTTP），优先 HTTP `http://127.0.0.1:8002`。

## 库表速查

| 表 | 含义 |
|----|------|
| inspection_tasks | 巡检任务 |
| inspection_task_shelves | 任务-货架顺序 |
| drones | 无人机 |
| shelves | 货架点位 |
| inventory_bindings | RFID↔SKU↔货架绑定 |
| qr_records | 二维码识别 |
| rfid_scan_records / rfid_scan_sessions | RFID 扫描 |
| drone_commands / drone_task_context | 无人机指令与上下文 |

## HTTP 只读接口（脚本不够时再用）

```bash
BASE=http://127.0.0.1:8002
curl -sS $BASE/api/health
curl -sS $BASE/api/tasks
curl -sS $BASE/api/tasks/TASK-166/qr-records
curl -sS $BASE/api/tasks/TASK-166/rfid-records
curl -sS $BASE/api/drones
curl -sS $BASE/api/shelves
curl -sS $BASE/api/inventory-bindings
curl -sS $BASE/api/qr-records
curl -sS $BASE/api/rfid/records
curl -sS $BASE/api/rfid/status
curl -sS $BASE/api/db/tables
curl -sS $BASE/api/db/tables/inspection_tasks
curl -sS -o /tmp/frame.jpg $BASE/api/frame/1/raw.jpg   # 取帧（视觉分析用）
```

## 写操作（默认禁止）

仅当用户**明确书面确认**且非飞行指令时，可考虑：
- `POST /api/inventory-bindings`（入库绑定）
- `POST /api/qr-control`（开关二维码检测）
- RFID connect/scan（占用读写器）

**绝不执行**任务 start/stop/abort 与起飞类指令。

## 汇报格式

1. 一句话结论
2. 关键数据（任务状态、电量、差异）
3. 盘点差异分「正确 / 放错 / 漏扫(缺失) / 多出」
4. 需人工操作时列出管理页步骤
