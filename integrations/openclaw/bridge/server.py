#!/usr/bin/env python3
"""OpenClaw bridge for Ground Lite sidebar assistant."""
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPENCLAW = os.environ.get(
    "OPENCLAW_BIN",
    os.path.expanduser("~/.local/node-v26.10.0-linux-arm64/bin/openclaw"),
)
PORT = int(os.environ.get("OPENCLAW_BRIDGE_PORT", "18080"))
SESSION_KEY = os.environ.get("OPENCLAW_SESSION_KEY", "agent:main:gcs")
TIMEOUT = int(os.environ.get("OPENCLAW_BRIDGE_TIMEOUT", "120"))
DEFAULT_MODEL = os.environ.get("OPENCLAW_BRIDGE_MODEL", "")


def extract_text(obj):
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj or None
    if isinstance(obj, dict):
        for k in ("finalAssistantVisibleText", "text", "reply", "answer", "message", "output"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for k in ("result", "payloads", "terminalReply", "data"):
            if k in obj:
                got = extract_text(obj[k])
                if got:
                    return got
    if isinstance(obj, list):
        for item in obj:
            got = extract_text(item)
            if got:
                return got
    return None


def run_agent(message: str, model: str = "") -> dict:
    model = (model or "").strip() or DEFAULT_MODEL
    cmd = [
        OPENCLAW, "agent",
        "--session-key", SESSION_KEY,
        "--message", message,
        "--timeout", str(TIMEOUT),
        "--json",
    ]
    if model:
        cmd.extend(["--model", model])
    env = os.environ.copy()
    env["PATH"] = os.path.dirname(OPENCLAW) + ":" + env.get("PATH", "")
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=TIMEOUT + 15, env=env, cwd=os.path.expanduser("~"),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "engine": "openclaw"}
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    try:
        data = json.loads(out)
        answer = extract_text(data)
        model_label = model
        try:
            meta = data.get("result", {}).get("meta", {}).get("agentMeta", {})
            provider = meta.get("provider") or ""
            m = meta.get("model") or ""
            if provider or m:
                model_label = f"{provider}/{m}".strip("/") or model
        except Exception:
            pass
        if answer:
            return {"ok": True, "answer": answer, "model": model_label, "engine": "openclaw"}
        if isinstance(data, dict) and p.returncode == 0:
            return {"ok": True, "answer": out, "model": model_label, "engine": "openclaw"}
    except Exception:
        pass
    return {
        "ok": p.returncode == 0 and bool(out),
        "answer": out or err or "OpenClaw 无输出",
        "model": model,
        "engine": "openclaw",
        "stderr": err[-500:],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": True, "bridge": "openclaw", "session": SESSION_KEY, "default_model": DEFAULT_MODEL})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/chat"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            message = (data.get("message") or "").strip()
            model = (data.get("model") or "").strip()
            if not message:
                self._send(400, {"ok": False, "error": "message required"})
                return
            self._send(200, run_agent(message, model))
        except Exception as exc:
            self._send(500, {"ok": False, "error": str(exc)})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        print("[bridge]", fmt % args, flush=True)


if __name__ == "__main__":
    print(f"OpenClaw bridge on :{PORT} session={SESSION_KEY} bin={OPENCLAW}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
