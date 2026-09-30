"""Ground Lite AI assistant via OpenClaw bridge (sidebar extension)."""
import json
import os
import sqlite3
import urllib.request
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/ai", tags=["ai"])

OPENCLAW_BRIDGE = os.environ.get("GROUND_LITE_OPENCLAW_BRIDGE", "http://172.19.0.1:18080")
FALLBACK_OLLAMA = os.environ.get("GROUND_LITE_OLLAMA_URL", "http://172.19.0.1:11434")
AI_MODEL = os.environ.get("GROUND_LITE_AI_MODEL", "")
AI_TIMEOUT = float(os.environ.get("GROUND_LITE_AI_TIMEOUT", "120"))
DB_PATH = os.environ.get("GROUND_LITE_DB", "/data/ground-lite.db")

# Curated OpenClaw routes (provider/model). Extend as needed.
OPENCLAW_MODELS = [
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek Chat (OpenClaw)", "engine": "openclaw", "source": "cloud"},
    {"id": "deepseek/deepseek-reasoner", "label": "DeepSeek Reasoner (OpenClaw)", "engine": "openclaw", "source": "cloud"},
    {"id": "ollama/llama3.2:3b", "label": "Llama 3.2 3B (OpenClaw+Ollama)", "engine": "openclaw", "source": "local"},
    {"id": "ollama/qwen3:8b", "label": "Qwen3 8B (OpenClaw+Ollama)", "engine": "openclaw", "source": "local"},
    {"id": "ollama/phi4-mini:3.8b", "label": "Phi-4 Mini (OpenClaw+Ollama)", "engine": "openclaw", "source": "local"},
    {"id": "ollama/qwen2.5vl:7b", "label": "Qwen2.5-VL 7B 视觉 (OpenClaw+Ollama)", "engine": "openclaw", "source": "local"},
]


class ChatRequest(BaseModel):
    message: str
    model: str | None = None


class ModelInfo(BaseModel):
    id: str
    label: str
    engine: str = "openclaw"
    source: str = "local"


def _rows(sql: str) -> List[Dict[str, Any]]:
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        data = [dict(r) for r in con.execute(sql).fetchall()]
        con.close()
        return data
    except Exception:
        return []


def _context() -> str:
    drones = _rows("select id, drone_code, name, status, battery_level from drones order by id limit 5")
    tasks = _rows(
        "select task_code, name, status, updated_at, status_reason from tasks order by updated_at desc limit 5"
    )
    shelves = _rows("select shelf_code, name from shelves order by shelf_code limit 15")
    return json.dumps(
        {"drones": drones, "recent_tasks": tasks, "shelves": shelves},
        ensure_ascii=False, default=str,
    )


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: float = 5) -> dict:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@router.get("/health")
def ai_health():
    engines = {}
    try:
        engines["openclaw"] = _get_json(OPENCLAW_BRIDGE.rstrip("/") + "/health")
    except Exception as exc:
        engines["openclaw"] = {"ok": False, "error": str(exc)}
    try:
        tags = _get_json(FALLBACK_OLLAMA.rstrip("/") + "/api/tags")
        engines["ollama"] = {"ok": True, "models": [m.get("name") for m in tags.get("models", [])]}
    except Exception as exc:
        engines["ollama"] = {"ok": False, "error": str(exc)}
    return {
        "ok": bool(engines.get("openclaw", {}).get("ok")),
        "engine": "openclaw",
        "bridge": OPENCLAW_BRIDGE,
        "engines": engines,
        "default_model": AI_MODEL,
        "label": "OpenClaw · 域感助理",
    }


@router.get("/models")
def ai_models():
    cloud = []
    local_openclaw = []
    local_fallback = []
    for m in OPENCLAW_MODELS:
        item = {
            "id": m["id"],
            "label": m["label"],
            "engine": m.get("engine", "openclaw"),
            "source": m.get("source", "local"),
            "group": "cloud" if m.get("source") == "cloud" else "local",
        }
        if item["group"] == "cloud":
            cloud.append(item)
        else:
            local_openclaw.append(item)
    try:
        tags = _get_json(FALLBACK_OLLAMA.rstrip("/") + "/api/tags")
        known = {m["id"] for m in OPENCLAW_MODELS}
        for m in tags.get("models", []):
            name = m.get("name")
            if not name:
                continue
            # skip if already exposed via openclaw ollama route
            if f"ollama/{name}" in known or name in known:
                # still list raw ollama as fallback? skip duplicates for cleaner UI
                continue
            local_fallback.append({
                "id": f"ollama-fallback:{name}",
                "label": name,
                "engine": "ollama",
                "source": "local",
                "group": "local",
            })
    except Exception:
        pass
    models = cloud + local_openclaw + local_fallback
    return {
        "ok": True,
        "models": models,
        "groups": {
            "cloud": {"label": "云端模型", "items": cloud},
            "local": {"label": "本地模型", "items": local_openclaw + local_fallback},
        },
        "default": AI_MODEL or (cloud[0]["id"] if cloud else (models[0]["id"] if models else "")),
    }


@router.post("/chat")
def ai_chat(req: ChatRequest):
    message = (req.message or "").strip()
    model = (req.model or "").strip()
    if not message:
        return {"ok": False, "answer": "请输入问题", "engine": "openclaw"}
    ctx = _context()
    prompt = (
        "你是域感助理。查询数据库请用 skill 脚本（快）：\n"
        "python3 /home/jetson/openclaw-workspace/skills/ground-lite/scripts/gl.py overview|tasks|task <code>|inventory|drones|shelves|bindings|qr|rfid|search <kw>|health\n"
        "禁止执行任务 start/stop/abort 等飞行指令。\n\n"
        "【地面站实时数据】\n" + ctx + "\n\n"
        "【操作员问题】\n" + message + "\n\n"
        "用简洁中文回答；数据已给出时优先直接汇总，需要更细再跑 gl.py。"
    )

    # Ollama direct / fallback model
    ollama_direct = None
    if model.startswith("ollama-fallback:"):
        ollama_direct = model.split(":", 1)[1]
        model = ""  # don't pass to OpenClaw

    # 1) OpenClaw bridge
    if not ollama_direct:
        try:
            data = _post_json(
                OPENCLAW_BRIDGE.rstrip("/") + "/chat",
                {"message": prompt, "model": model},
                AI_TIMEOUT,
            )
            answer = data.get("answer") or data.get("error") or "（无回答）"
            return {
                "ok": True,
                "engine": "openclaw",
                "answer": answer,
                "model": data.get("model") or model or "openclaw",
                "label": "OpenClaw",
            }
        except Exception as primary_err:
            fallback_err = primary_err
    else:
        fallback_err = "ollama-direct"

    # 2) Ollama fallback
    try:
        ollama_model = ollama_direct or (model.split("/", 1)[-1] if model.startswith("ollama/") else (model or AI_MODEL or "llama3.2:3b"))
        payload = {
            "model": ollama_model,
            "prompt": "你是仓库巡检助理，用简洁中文回答。\n" + prompt,
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 512},
        }
        j = _post_json(FALLBACK_OLLAMA.rstrip("/") + "/api/generate", payload, AI_TIMEOUT)
        return {
            "ok": True,
            "engine": "ollama",
            "answer": (j.get("response") or "").strip(),
            "model": ollama_model,
            "label": "Ollama",
            "note": "" if ollama_direct else f"OpenClaw 不可用: {fallback_err}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "engine": "none",
            "answer": f"AI 调用失败：OpenClaw({fallback_err}) / Ollama({exc})",
        }
