# Ground Lite 地面站（轻量版）

FastAPI + SQLite + UDP 视频 + RFID/二维码巡检。

- `app/main.py`：主服务
- `app/ai_chat.py`：OpenClaw/Ollama AI 助理 API
- `app/static/`：管理页（含侧边栏 AI 助理）

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| GROUND_LITE_DB | /data/ground-lite.db | SQLite 路径 |
| GROUND_LITE_OPENCLAW_BRIDGE | http://127.0.0.1:18080 | OpenClaw 桥接 |
| GROUND_LITE_OLLAMA_URL | http://127.0.0.1:11434 | Ollama |
| GROUND_LITE_RFID_PORT | /dev/ttyUSB0 | RFID 串口 |
| GROUND_LITE_UDP_SOURCE | udp://@:5600 | 视频流 |

运行数据、密钥、`.env` 勿入库。
