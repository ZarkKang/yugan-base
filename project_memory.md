# 项目记忆 — 域感智能

## 核心约定
- 启动管理使用 `启动.sh`（统一脚本），`./启动.sh` 一键启动，`./启动.sh menu` 交互菜单。`引导.sh` 为兼容性包装器。
- 所有后台线程必须随 FastAPI `lifespan` shutdown 事件优雅退出（如 RFID 连续扫描、入库监听）。
- 禁止在路由中直接 `return` 错误 — 异常由全局 `exception_handler` 统一捕获。
- 日志统一使用 `logging.getLogger(__name__)`，禁止 `print()`。
- 新增 API 必须返回 `APIResponse(success=..., message=..., data=...)` 格式。

## 目录结构约定（2026-06-30 整理）
- **日志目录**: `logs/` — 统一存放日志文件
  - `logs/devlog.md` — 开发日志（重要变更时序记录）
  - `logs/review/` — 复盘报告目录（现状-期望分析报告）
  - `logs/runtime/` — 运行日志目录（服务运行时 *.log 文件，如 drone.log、warehouse.log）
- **文档目录**: `doc/` — 统一存放技术文档（不再使用 docs/）
  - `doc/drone/` — 无人机端文档（开发规范、payload 代码等）
  - `doc/specs/` — 规范文档
  - `doc/plans/` — 计划文档
  - `doc/progress/` — 开发进度文档
- **项目记忆**: `project_memory.md` — 根目录保留，存放核心约定和关键信息
- **注意**: 不要再创建 docs/ 目录，所有文档统一放入 doc/

## 关键表结构速查

### RFIDTag（EPC → 商品映射）
| 字段 | 说明 |
|------|------|
| `tag_id` | EPC 标签号（hex 大写，**入库查询键**） |
| `goods_name` | 商品名称（即 SKU 标识） |
| `shelf_id` | 关联货架 |

### Inventory（RFID 实时库存快照）
| 字段 | 说明 |
|------|------|
| `rfid_tag_id` | FK → rfid_tags.id, **unique** |
| `quantity` | 当前库存数量 |
| `last_read_at` | 最后 RFID 读取时间 |

### InboundRecord（入库流水）
| 字段 | 说明 |
|------|------|
| `epc` | RFID 读到的 EPC 号 |
| `status` | success / failed |
| `message` | 失败原因 |

## PRE 系列 RFID 模块协议速查

| 功能 | 命令码 | 说明 |
|------|--------|------|
| 单次盘存 | `0x04` | 返回 TYPE_INFO 通知帧 |
| 多次盘存 | `0x08` | loop=0 表示无限 |
| 停止盘存 | `0x09` | |
| 设置功率 | `0x0A` | power_dbm*100, 2B |
| 锁定/解锁 | `0x0E` | |
| 杀死标签 | `0x0F` | |
| 帧头 | `0xBB` | |
| 帧尾 | `0x7E` | |

EPC 解析公式：`pc_byte0 = params[1]`, `epc_len = ((pc_byte0 // 8) + 1) * 2 - 2`

帧格式：`BB + Type(1) + Cmd(1) + PL(2,big-endian) + Params(N) + CS(1,sum%256) + 7E`

## 已知陷阱
- Windows 编辑的 `.sh` 脚本在 WSL 运行前必须转 LF，否则 bash 解析 shebang 失败（报 `$'\r': command not found` 或 `required file not found`）。项目已统一转换，但新增/编辑 shell 脚本时需确保编辑器使用 LF 换行符。
- WSL 环境不支持 pyserial，需用 fd 直接打开 `/dev/ttyS*`，`select.select()` 做非阻塞读。
- 入库服务的 `_on_tag_detected` 回调在后台线程中执行，需自行创建 `SessionLocal()` 管理数据库会话，**不能使用 FastAPI 的 `get_db` 依赖注入**。
- Python 环境未安装或不在 PATH 时，`pytest` 无法直接从命令行运行。
- drone-db-prototype 所有路由强制 JWT 认证（`OAuth2PasswordBearer`），前端必须通过 `POST /api/auth/login` 获取 token 后存入 localStorage，否则所有请求返回 401。
- warehouse-inspection-system 路由不强制认证，但前端同样配了自动登录机制以保持一致。
- 默认管理员账号: `admin / CHANGE_ME_DB_PASSWORD`（需确认 seed 数据已创建）。

## RFID 连接故障排查速查
1. `GET /api/v1/rfid/diagnose` — 诊断端点，检查 pyserial、串口列表、连接状态
2. CP2102 驱动下载: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
3. PRE 模块默认波特率 115200，auto_detect 会依次尝试 [115200,9600,38400,19200,57600]
4. WSL 下串口路径 `/dev/ttyS<N>`，Windows 下为 `COM<N>`
5. 常见失败: 模块未通电 / CP2102 驱动未装 / COM 口被 Demo 软件占用
6. 部署脚本已自动处理：`deploy-linux.sh` 和 `引导.sh` 快速部署会自动 `sudo chmod 666` 并加入 `dialout` 组

## 入库流程
```
RFID 读标签 → EPC hex
  → `SELECT * FROM rfid_tags WHERE tag_id = epc`
  → 找到: UPSERT inventory (quantity += 1) + INSERT inbound_records (status=success)
  → 未找到: INSERT inbound_records (status=failed, message="未注册")
```

## WS 图传协议速查

| 项 | 值 |
|----|----|
| 端点 | `ws://192.168.1.200:8080/ws/video/{drone_id}`（经 api-gateway） |
| 直连端点 | `ws://192.168.1.200:8001/ws/video/{drone_id}`（warehouse 直连，仅内网测试用） |
| 帧消息 | binary（JPEG 字节流，无包装） |
| 控制消息 | text（JSON，必含 `type` 字段） |
| 控制消息类型 | `stream_start` / `waypoint_enter` / `waypoint_leave` / `stream_stop` / `heartbeat` |
| 默认 FPS | 15 |
| 单文件策略 | 一次 WS 会话 = 一个 mp4 文件 + 一个 VideoData 行 |
| 航点不切分 | 到达航点仅追加 `waypoint_markers` JSON 数组项，不切分视频 |
| 网络降级 | WS 不稳定时无人机回退 `POST /api/v1/videos/upload` |
| 实现文件 | `services/video_stream_aggregator.py` + `api/ws_video.py` + `app/api-gateway/main.py:277` |

## 无人机端 API 命名空间约定（2026-07-06 统一）

- **所有无人机→基站的 HTTP 接口**统一到 `/api/drones/` 命名空间，实现在 `api/drone_api.py`
  - 两个路由：`router`（prefix `/api/drones`）+ `waypoints_router`（prefix `/api`，仅 `/api/tasks/{task_code}/waypoints`）
- **路径参数使用 `drone_id`（整数 PK）**，不再使用 `drone_code`（字符串）
- **drone_id 获取方式**：无人机通过 `GET /api/drones/lookup?drone_code=xxx` 反查得到整数 `drone_id`，缓存后用于后续所有请求
- **WS 图传端点**同样使用 `drone_id`：`ws://.../ws/video/{drone_id}`
- **api-gateway 代理**：`/api/drones/{path}` → warehouse `/api/drones/{path}`；`/api/tasks/{path}` (GET) → warehouse `/api/tasks/{path}`
- **已删除的旧端点**：`drones.py` 的 `GET /{drone_id}/position` 和 `POST /{drone_code}/heartbeat`；`inspection.py` 的 5 个无人机端点；`gateway.py` 的 `POST /shelves/sync`
- **前端 CRUD 端点**仍在 `api/drones.py`，不受影响

## 无人机端兼容性备注（2026-07-06）

根据 `doc/2026-07-06_REAL_DRONE_400_changes.md`，无人机端 5 条链路的实际行为与基站端原始设计有差异，基站已做兼容处理：

1. **心跳误路由**：无人机当前 `heartbeat_path` 配置为 `shelves/sync`，心跳数据 `{drone_code, position, status, battery, timestamp}` 发到货架同步端点。基站端 `sync_shelves_from_drone()` 入口检测 `shelves 为空 + timestamp 存在` 时自动路由到心跳处理逻辑（`_handle_misrouted_heartbeat`），防止货架被误归档。
2. **waypoint_id 语义冲突**：无人机发送货柜编号（如 `01-01`）作为路径中的 `waypoint_id`，但基站 `Waypoint.id` 格式为 `wp_xxx`。`waypoint_arrive()` 先按 `Waypoint.id` 查询，查不到时自动按 `Waypoint.shelf_code + task_code` 回退查询。
3. **RFID 上传**：新增 `POST /api/drones/{drone_id}/rfid/upload`，灵活解析 `List[dict]` payload，支持多种字段名（rfid_tag/epc/tag_id）。
4. **状态映射**：无人机 `running`→基站 `flying`，`completed`→`idle`。在 `drone_heartbeat()` 和 `_handle_misrouted_heartbeat()` 中均做映射。
5. **时间戳转换**：无人机用 Unix 时间戳（float 秒），基站自动 `datetime.fromtimestamp()` 转换。
6. **position 兜底**：航点到达时若无人机未传 position，从 `Waypoint` 表读取坐标用于 clip 位置校验。

## QR 双图保存路径约定

- 裁剪 QR 区域小图：`storage/qr_crops/{task_id_or_no_task}/{waypoint_id_or_no_wp}/crop_{image_id}_{yyyyMMdd_HHmmss}.jpg`
- 带 QR 框选标注的原图：`storage/qr_crops/{task_id_or_no_task}/{waypoint_id_or_no_wp}/annotated_{image_id}_{yyyyMMdd_HHmmss}.jpg`
- 仅在 QR 命中时保存（`qr_text is not None`），未命中两字段保持 NULL
- 实现入口：`image/qr_worker.py:_save_qr_evidence_images()`，复用 `image/annotator.draw_qr_bbox()` + `image/crop.save_image()`
- 数据库字段：`ImageRecord.qr_cropped_path` / `ImageRecord.annotated_path`

## VideoData.source 字段语义

| 取值 | 含义 | 上传通道 | 触发后处理 |
|------|------|---------|-----------|
| `upload` | 无人机 multipart 文件上传 | `POST /api/v1/videos/upload` | `videos.py:_process_video_background` → `postprocess_video(source="upload")` |
| `gateway` | 无人机经 gateway Base64 上传 | `POST /api/warehouse/videos/...` | `gateway.py:_process_video_in_background` → `postprocess_video(source="gateway")` |
| `ws_stream` | 无人机 WS 实时图传 | `WS /ws/video/{drone_id}` | `video_stream_aggregator.close_session()` → `postprocess_video(source="ws_stream")` |
| `waypoint_clip` | 航点到达触发的视频截取片段 | `WS 推流中旁路截取` | `DroneStreamSession._finish_clip()` → `postprocess_video(source="waypoint_clip")` |

四条通道最终汇入 `services/video_postprocess.postprocess_video()` 公共管线，保证 QR 识别 + InventoryItem 写入 + 交叉校验逻辑一致。

## 未来计划
- Alembic 数据库迁移（当前未集成，P3 优先级）
- Gateway 端到端测试
- 模拟器全流程测试