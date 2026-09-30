#!/usr/bin/env python3
"""ground-lite helper for OpenClaw skill.

普通指令：任务发布、盘点、绑定、库表、查询 —— 直接执行。
敏感指令（start/takeoff/arm/unlock 等）：必须带 --key 且与本机密钥一致。
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("GROUND_LITE_BASE", "http://127.0.0.1:8002")
KEY_FILE = Path(os.environ.get("GL_SENSITIVE_KEY_FILE", Path.home() / ".openclaw/secrets/gcs-safety.key"))

SENSITIVE = {
    "start", "start-task", "takeoff", "take-off", "arm", "unlock", "launch",
    "clear-table", "clear-bindings", "drop",
    "起飞", "解锁",
}


def load_key() -> str:
    env = os.environ.get("GL_SENSITIVE_KEY", "").strip()
    if env:
        return env
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def extract_key(argv):
    key = os.environ.get("GL_SENSITIVE_KEY", "").strip()
    out = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--key", "-k") and i + 1 < len(argv):
            key = argv[i + 1]
            i += 2
            continue
        if a.startswith("--key="):
            key = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    return key, out


def check_sensitive(cmd: str, key: str) -> bool:
    if cmd not in SENSITIVE and cmd.replace("_", "-") not in SENSITIVE:
        return True
    expected = load_key()
    if not expected:
        print("ERROR: 本机未配置敏感指令密钥，无法执行:", cmd)
        return False
    if key == expected:
        return True
    print("DENIED: 敏感指令需要正确密钥。用法示例:")
    print("  gl.py start TASK-202 --key <密钥>")
    print("  （密钥由操作员在对话中提供，校验失败不会执行）")
    return False


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode("utf-8", "ignore")[:400]}
    except Exception as e:
        return {"error": str(e)}


def send(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode("utf-8", "ignore")[:400]}
    except Exception as e:
        return {"error": str(e)}


def fmt_ts(v):
    if not v:
        return "-"
    try:
        import datetime
        return datetime.datetime.fromtimestamp(float(v)).strftime("%m-%d %H:%M")
    except Exception:
        return str(v)


def as_list(x):
    if isinstance(x, dict):
        return x.get("data") or x.get("items") or x.get("rows") or []
    return x or []


def cmd_overview():
    drones = as_list(get("/api/drones"))
    tasks = as_list(get("/api/tasks"))
    shelves = as_list(get("/api/shelves"))
    bindings = as_list(get("/api/inventory-bindings"))
    print("=== 无人机 ===")
    for d in drones[:5]:
        print(f"  #{d.get('id')} {d.get('drone_code')} status={d.get('status')} battery={d.get('battery_level')}")
    print("=== 最近任务 ===")
    for t in tasks[:5]:
        print(f"  {t.get('task_code')} status={t.get('status')} shelves={t.get('shelf_ids')}")
    print(f"=== 货架 {len(shelves)} / 绑定 {len(bindings)} ===")


def cmd_tasks(n=5):
    for t in as_list(get("/api/tasks"))[: int(n)]:
        print(f"{t.get('task_code')} | {t.get('status')} | drone={t.get('drone_id')} | {fmt_ts(t.get('updated_at'))} | {t.get('status_reason') or ''}")
        print(f"   shelves: {t.get('shelf_ids')}")


def cmd_task(code):
    for t in as_list(get("/api/tasks")):
        if t.get("task_code") == code:
            print(json.dumps(t, ensure_ascii=False, indent=2))
            return
    print("NOT_FOUND", code)


def cmd_publish_task(args):
    if len(args) < 1:
        print("usage: gl.py publish-task TASK-001 [name] [drone_id] 01-01,02-01")
        return
    task_code = args[0]
    name = task_code
    drone_id = 1
    shelf_ids = []
    rest = args[1:]
    if rest and rest[0].isdigit():
        drone_id = int(rest[0])
        rest = rest[1:]
    if rest and not rest[0].isdigit() and "," not in rest[0] and not (rest[0].count("-") == 1 and rest[0][0].isdigit()):
        name = rest[0]
        rest = rest[1:]
    if rest and rest[0].isdigit():
        drone_id = int(rest[0])
        rest = rest[1:]
    for token in rest:
        for part in str(token).split(","):
            part = part.strip()
            if part:
                shelf_ids.append(part)
    body = {"task_code": task_code, "name": name, "drone_id": drone_id, "shelf_ids": shelf_ids}
    print(json.dumps(send("POST", "/api/tasks", body), ensure_ascii=False, indent=2)[:2000])


def cmd_start(args):
    """Sensitve: start task (requires --key)."""
    if not args:
        print("usage: gl.py start TASK-xxx --key <密钥>")
        return
    code = args[0]
    res = send("POST", f"/api/tasks/{code}/start")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:2000])


def cmd_stop(args):
    if not args:
        print("usage: gl.py stop TASK-xxx")
        return
    res = send("POST", f"/api/tasks/{args[0]}/stop")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:1500])


def cmd_task_qr(code):
    print(json.dumps(get(f"/api/tasks/{code}/qr-records"), ensure_ascii=False, indent=2)[:4000])


def cmd_task_rfid(code):
    print(json.dumps(get(f"/api/tasks/{code}/rfid-records"), ensure_ascii=False, indent=2)[:4000])


def cmd_drones():
    print(json.dumps(get("/api/drones"), ensure_ascii=False, indent=2)[:3000])


def cmd_shelves():
    print(json.dumps(get("/api/shelves"), ensure_ascii=False, indent=2)[:3000])


def cmd_bindings():
    print(json.dumps(get("/api/inventory-bindings"), ensure_ascii=False, indent=2)[:4000])


def cmd_bind(args):
    if len(args) < 3:
        print("usage: gl.py bind RFID SKU SHELF")
        return
    print(json.dumps(send("POST", "/api/inventory-bindings", {"rfid": args[0], "sku": args[1], "shelf_code": args[2]}), ensure_ascii=False, indent=2)[:1500])


def cmd_unbind(args):
    if not args:
        print("usage: gl.py unbind <id>")
        return
    print(json.dumps(send("DELETE", f"/api/inventory-bindings/{int(args[0])}"), ensure_ascii=False))


def cmd_clear_bindings():
    print(json.dumps(send("DELETE", "/api/inventory-bindings", {"confirm": "inventory_bindings"}), ensure_ascii=False))


def cmd_qr(n=10):
    data = get("/api/qr-records")
    if isinstance(data, list):
        data = data[: int(n)]
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])


def cmd_rfid(n=10):
    data = get("/api/rfid/records")
    if isinstance(data, list):
        data = data[: int(n)]
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])


def cmd_rfid_status():
    print(json.dumps(get("/api/rfid/status"), ensure_ascii=False, indent=2)[:2000])


def cmd_qr_control(args):
    if not args:
        print(json.dumps(get("/api/qr-control"), ensure_ascii=False, indent=2))
        return
    enabled = args[0].lower() in ("on", "1", "true", "enable")
    print(json.dumps(send("POST", "/api/qr-control", {"enabled": enabled}), ensure_ascii=False, indent=2)[:1500])


def cmd_inventory():
    bindings = as_list(get("/api/inventory-bindings"))
    qr = as_list(get("/api/qr-records"))
    rfid = as_list(get("/api/rfid/records"))
    tasks = as_list(get("/api/tasks"))[:3]
    for t in tasks:
        code = t.get("task_code")
        if not code:
            continue
        extra_qr = as_list(get(f"/api/tasks/{code}/qr-records"))
        extra_rfid = as_list(get(f"/api/tasks/{code}/rfid-records"))
        if extra_qr and isinstance(extra_qr, list):
            qr = extra_qr + [x for x in qr if x.get("task_code") != code]
        if extra_rfid and isinstance(extra_rfid, list):
            rfid = extra_rfid + [x for x in rfid if x.get("task_code") != code]

    bind_by_sku = {b.get("sku"): b for b in bindings if b.get("sku")}
    bind_by_rfid = {b.get("rfid"): b for b in bindings if b.get("rfid")}
    qr_set, seen_sku = set(), set()
    correct, wrong_shelf, missing, extra = [], [], [], []

    for q in qr:
        sku = q.get("text") or q.get("sku") or ""
        shelf = q.get("shelf_code") or ""
        if not sku:
            continue
        seen_sku.add(sku)
        qr_set.add(sku)
        b = bind_by_sku.get(sku)
        if not b:
            extra.append((sku, shelf or "-", "未绑定/多出"))
            continue
        b_shelf = b.get("shelf_code")
        if b_shelf and shelf and b_shelf != shelf:
            wrong_shelf.append((sku, shelf, b_shelf))
        else:
            correct.append((sku, shelf or b_shelf))

    for r in rfid:
        rid = r.get("rfid") or r.get("epc") or ""
        b = bind_by_rfid.get(rid)
        if b and b.get("sku") and b.get("sku") not in seen_sku:
            missing.append((b.get("sku"), rid, "有RFID无二维码"))

    for b in bindings:
        sku = b.get("sku")
        if sku and sku not in qr_set and sku not in {x[0] for x in missing}:
            missing.append((sku, b.get("rfid"), "任务结果未出现"))

    print("=== 盘点判定 ===")
    print(f"正确: {len(correct)}")
    for x in correct[:30]:
        print("  OK", x)
    print(f"放错: {len(wrong_shelf)}")
    for x in wrong_shelf[:30]:
        print("  WRONG", x)
    print(f"疑似缺失/漏扫: {len(missing)}")
    for x in missing[:30]:
        print("  MISS", x)
    print(f"多出/未绑定: {len(extra)}")
    for x in extra[:30]:
        print("  EXTRA", x)



def cmd_delete_rows(args):
    """delete-rows TABLE id1,id2,...  (single row delete)"""
    if len(args) < 2:
        print("usage: gl.py delete-rows TABLE 1,2,3")
        return
    table = args[0]
    ids = []
    for tok in args[1:]:
        for part in str(tok).split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
    if not ids:
        print("no valid ids")
        return
    print(json.dumps(send("DELETE", f"/api/db/tables/{table}", {"ids": ids}), ensure_ascii=False, indent=2)[:1500])


def cmd_clear_table(args):
    """clear-table TABLE --key <密钥>   wipe whole table (destructive)"""
    if not args:
        print("usage: gl.py clear-table TABLE --key <密钥>")
        return
    table = args[0]
    print(json.dumps(send("DELETE", f"/api/db/tables/{table}", {"confirm": table}), ensure_ascii=False, indent=2)[:1500])


def cmd_delete_task(args):
    """delete-task TASK-xxx  (best-effort: clear related rows via ids if possible)"""
    if not args:
        print("usage: gl.py delete-task TASK-xxx")
        return
    code = args[0]
    # inspection_tasks PK is task_code (no id) -> cannot delete single row via API ids.
    # delete inspection_task_shelves rows for this task (has id), and report how to clear tasks.
    rows = as_list(get("/api/db/tables/inspection_task_shelves?limit=500"))
    ids = []
    for r in rows:
        if r.get("task_code") == code and r.get("id") is not None:
            ids.append(int(r["id"]))
    out = {"task_code": code, "task_shelves_deleted": 0, "note": ""}
    if ids:
        res = send("DELETE", "/api/db/tables/inspection_task_shelves", {"ids": ids})
        out["task_shelves_deleted"] = res.get("deleted", len(ids)) if isinstance(res, dict) else 0
        out["task_shelves_result"] = res
    out["note"] = (
        "inspection_tasks 无 id 列，单条任务无法按 id 删除。"
        "若要删除任务记录本体，用 clear-table inspection_tasks（需密钥，清空全部任务）"
        "或在管理页数据库查看中操作。"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2)[:2000])


def cmd_db(args):
    if not args:
        print("usage: gl.py db tables|rows|export")
        return
    sub = args[0]
    if sub == "tables":
        print(json.dumps(get("/api/db/tables"), ensure_ascii=False, indent=2)[:4000])
    elif sub == "rows":
        if len(args) < 2:
            print("usage: gl.py db rows TABLE [limit]")
            return
        limit = args[2] if len(args) > 2 else "50"
        print(json.dumps(get(f"/api/db/tables/{args[1]}?limit={limit}"), ensure_ascii=False, indent=2)[:5000])
    elif sub == "export":
        if len(args) < 2:
            print("usage: gl.py db export TABLE")
            return
        try:
            with urllib.request.urlopen(BASE + f"/api/db/tables/{args[1]}/export", timeout=15) as r:
                print(r.read().decode("utf-8", "ignore")[:4000])
        except Exception as e:
            print("export error", e)
    else:
        print("unknown db sub", sub)


def cmd_search(kw):
    kw = (kw or "").lower()
    for path, name in (("/api/tasks", "task"), ("/api/shelves", "shelf"), ("/api/inventory-bindings", "binding")):
        for item in as_list(get(path)):
            if kw in json.dumps(item, ensure_ascii=False).lower():
                print(f"[{name}]", json.dumps(item, ensure_ascii=False)[:300])


def cmd_health():
    print(json.dumps(get("/api/health"), ensure_ascii=False, indent=2)[:2000])


def usage():
    print("""usage: gl.py <cmd> [args] [--key 密钥]

查询: overview|tasks|task|task-qr|task-rfid|drones|shelves|bindings|qr|rfid|inventory|search|health
任务: publish-task TASK-xxx [name] [drone_id] shelf1,shelf2
盘点: bind|unbind|clear-bindings|qr-control
库表: db tables|rows|export
删除: delete-rows TABLE 1,2,3 | delete-task TASK-xxx | clear-table TABLE（需密钥）

敏感指令（需 --key，密钥由操作员在对话中提供）:
  start TASK-xxx --key <密钥>     # 启动任务/下发航线
  takeoff / arm / unlock          # 同类解锁起飞语义

密钥校验失败则拒绝执行。
""")


def main():
    if len(sys.argv) < 2:
        usage()
        return
    key, argv = extract_key(sys.argv[1:])
    cmd = argv[0]
    args = argv[1:]
    if not check_sensitive(cmd, key):
        sys.exit(2)

    handlers = {
        "overview": lambda: cmd_overview(),
        "tasks": lambda: cmd_tasks(args[0] if args else 5),
        "task": lambda: cmd_task(args[0] if args else ""),
        "task-qr": lambda: cmd_task_qr(args[0] if args else ""),
        "task-rfid": lambda: cmd_task_rfid(args[0] if args else ""),
        "drones": cmd_drones,
        "shelves": cmd_shelves,
        "bindings": cmd_bindings,
        "qr": lambda: cmd_qr(args[0] if args else 10),
        "rfid": lambda: cmd_rfid(args[0] if args else 10),
        "rfid-status": cmd_rfid_status,
        "inventory": cmd_inventory,
        "search": lambda: cmd_search(args[0] if args else ""),
        "health": cmd_health,
        "publish-task": lambda: cmd_publish_task(args),
        "start": lambda: cmd_start(args),
        "start-task": lambda: cmd_start(args),
        "stop": lambda: cmd_stop(args),
        "bind": lambda: cmd_bind(args),
        "unbind": lambda: cmd_unbind(args),
        "clear-bindings": cmd_clear_bindings,
        "delete-rows": lambda: cmd_delete_rows(args),
        "delete-row": lambda: cmd_delete_rows(args),
        "clear-table": lambda: cmd_clear_table(args),
        "delete-task": lambda: cmd_delete_task(args),
        "drop": lambda: cmd_clear_table(args),
        "qr-control": lambda: cmd_qr_control(args),
        "db": lambda: cmd_db(args),
        "takeoff": lambda: cmd_start(args),
        "arm": lambda: cmd_start(args),
        "unlock": lambda: cmd_start(args),
    }
    fn = handlers.get(cmd)
    if not fn:
        print("unknown", cmd)
        usage()
        return
    fn()


if __name__ == "__main__":
    main()
