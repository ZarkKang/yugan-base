# OpenClaw × Ground Lite 集成说明

将 OpenClaw 作为地面站管理页的 AI 助理扩展（侧边栏内嵌）。

## 架构

```
管理页「AI 助理」
    → ground-lite /api/ai/chat
        → OpenClaw Bridge (:18080)
            → openclaw agent
                → 模型（云端 API / 本地 Ollama）
                → skill: ground-lite（scripts/gl.py 一键查库）
        → 失败时 Ollama 兜底
```

## 目录

| 路径 | 说明 |
|------|------|
| `station/ground-lite/app/` | 地面站后端 + 前端（含 AI 面板） |
| `station/ground-lite/app/ai_chat.py` | `/api/ai/*` 模型列表与对话 |
| `station/ground-lite/app/static/assistant.*` | 侧边栏 AI 助理 UI |
| `integrations/openclaw/bridge/server.py` | OpenClaw HTTP 桥接 |
| `integrations/openclaw/skills/ground-lite/` | OpenClaw skill + `gl.py` |

## 部署要点

1. 安装 OpenClaw（Node 24/26+），完成 onboard，接入 Ollama 或云端模型。
2. 配置 Gateway 为局域网可访问（`gateway.bind=lan`）。
3. 启动桥接服务：

```bash
export PATH=<node26>/bin:$PATH
python3 integrations/openclaw/bridge/server.py
# 或 systemd user: openclaw-bridge
```

4. ground-lite 环境变量（按需）：

```bash
GROUND_LITE_OPENCLAW_BRIDGE=http://127.0.0.1:18080
GROUND_LITE_OLLAMA_URL=http://127.0.0.1:11434
GROUND_LITE_AI_MODEL=  # 空则用用户在 UI 选择的模型
```

5. 安装 skill 到 OpenClaw workspace：

```bash
openclaw skills install integrations/openclaw/skills/ground-lite --as ground-lite --force
```

## 安全约定

- **禁止**通过 AI 执行任务 `start` / `stop` / `abort` 等飞行指令。
- 密钥一律走环境变量 / 密钥文件，禁止写入仓库。
- 本仓库所有口令均为 `CHANGE_ME_*` 占位符，部署前必须替换。

## 模型

- 云端：DeepSeek 等 OpenAI 兼容接口（`models.providers.*`）
- 本地：Ollama（llama3.2 / qwen3 / qwen2.5vl 等）
- UI 下拉框按「云端模型 / 本地模型」分组，选择对下一条消息生效。
