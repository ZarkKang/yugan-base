# OpenClaw 集成

- `bridge/server.py`：HTTP 桥接，调用 `openclaw agent`，供 ground-lite `/api/ai/chat` 使用。
- `skills/ground-lite/`：OpenClaw 技能；`scripts/gl.py` 一键查询任务/盘点/绑定等，禁止飞行类写操作。

密钥与网关 Token 请在运行环境配置，不要提交到本仓库。
