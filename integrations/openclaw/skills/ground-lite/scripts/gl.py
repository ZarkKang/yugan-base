#!/usr/bin/env python3
"""ground-lite one-shot helper for OpenClaw skill.

AI 可用：任务发布、盘点判定、绑定维护、库表查看、只读查询。
AI 禁止：任务 start、起飞/解锁/START_MISSION 等飞行指令。
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8002"

# Commands that unlock/take off the drone — AI must never call these.
FORBIDDEN_SUBSTRINGS = (
    "start", "START_MISSION", "takeoff", "take_off", "arm", "unlock",
    "launch", "起飞", "解锁", "disarm",
)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode("utf-8", "ignore")[:400]}
    except Exception as e:
        return {"error": str(e)}


def send(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode("utf-8", "ignore")[:400]}
    except Exception as e:
        return {"error": str(e)}


def guard_forbidden(cmd_name, extra=""):
    text = (cmd_name + " " + extra).lower()
    # allow commands that merely mention reading task-qr etc.
    hard = ("start", "takeoff", "take-off", "arm", "unlock", "launch")
    # only block when the command itself is a flight command
    if cmd_name in ("start", "start-task", "takeoff", "arm", "unlock"):
        print("FORBIDDEN: AI 不允许执行解锁起飞/任务启动指令，请在管理页人工操作。")
        sys.exit(2)
    if "start_task" in cmd_name or cmd_name.endswith("/start"):
        print("FORBIDDEN: AI 不允许执行解锁起飞/任务启动指令。")
        sys.exit(2)


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
        print(f"  {t.get('task_code')} status={t.get('status')} shelves={t.get('shelf_ids')} reason={t.get('status_reason')}")
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
    """publish-task TASK-001 [name] [drone_id] shelf1,shelf2,..."""
    if len(args) < 2:
        print("usage: gl.py publish-task TASK-001 [name] [drone_id] 01-01,02-01")
        return
    task_code = args[0]
    name = args[1] if len(args) > 1 and not args[1].isdigit() else task_code
    drone_id = 1
    shelf_ids = []
    # parse flexible: remaining tokens may include drone_id and shelves
    rest = args[1:]
    if rest and rest[0].isdigit():
        drone_id = int(rest[0])
        rest = rest[1:]
    elif len(args) >= 3 and args[2].isdigit():
        drone_id = int(args[2])
        rest = args[3:]
    for token in rest:
        if "," in token:
            shelf_ids.extend([x.strip() for x in token.split(",") if x.strip()])
        elif token and not token.isdigit() and "-" in token:
            shelf_ids.append(token)
        elif token and not token.isdigit() and token != name:
            # maybe name already used
            pass
    body = {
        "task_code": task_code,
        "name": name if name != task_code else task_code,
        "drone_id": drone_id,
        "shelf_ids": shelf_ids,
    }
    res = send("POST", "/api/tasks", body)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:2000])


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
    """bind RFID SKU SHELF"""
    if len(args) < 3:
        print("usage: gl.py bind EPC-001 SKU-001 01-01")
        return
    rfid, sku, shelf = args[0], args[1], args[2]
    res = send("POST", "/api/inventory-bindings", {"rfid": rfid, "sku": sku, "shelf_code": shelf})
    print(json.dumps(res, ensure_ascii=False, indent=2)[:1500])


def cmd_unbind(args):
    if not args:
        print("usage: gl.py unbind <binding_id>")
        return
    res = send("DELETE", f"/api/inventory-bindings/{int(args[0])}")
    print(json.dumps(res, ensure_ascii=False))


def cmd_clear_bindings():
    res = send("DELETE", "/api/inventory-bindings", {"confirm": "inventory_bindings"})
    print(json.dumps(res, ensure_ascii=False))


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
    """qr-control on|off"""
    if not args:
        print(json.dumps(get("/api/qr-control"), ensure_ascii=False, indent=2))
        return
    enabled = args[0].lower() in ("on", "1", "true", "enable")
    res = send("POST", "/api/qr-control", {"enabled": enabled})
    print(json.dumps(res, ensure_ascii=False, indent=2)[:1500])


def cmd_inventory():
    bindings = as_list(get("/api/inventory-bindings"))
    qr = as_list(get("/api/qr-records"))
    rfid = as_list(get("/api/rfid/records"))
    # also try task-tagged qr if any recent tasks
    tasks = as_list(get("/api/tasks"))[:3]
    for t in tasks:
        code = t.get("task_code")
        if not code:
            continue
        extra_qr = as_list(get(f"/api/tasks/{code}/qr-records"))
        extra_rfid = as_list(get(f"/api/tasks/{code}/rfid-records"))
        # merge if list of dicts
        if extra_qr and isinstance(extra_qr, list):
            qr = extra_qr + [x for x in qr if x.get("task_code") != code]
        if extra_rfid and isinstance(extra_rfid, list):
            rfid = extra_rfid + [x for x in rfid if x.get("task_code") != code]

    bind_by_sku = {b.get("sku"): b for b in bindings if b.get("sku")}
    bind_by_rfid = {b.get("rfid"): b for b in bindings if b.get("rfid")}
    qr_set = set()
    rfid_set = set()

    correct, wrong_shelf, missing, extra = [], [], [], []
    seen_sku = set()

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
        if rid:
            rfid_set.add(rid)
        # match by rfid to binding sku
        b = bind_by_rfid.get(rid)
        if b and b.get("sku") in seen_sku:
            continue
        # if rfid recorded but no corresponding qr sku
        if b and b.get("sku") not in seen_sku:
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


def cmd_db(args):
    """db tables | db rows TABLE [limit] | db export TABLE"""
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
        # export returns csv
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
            blob = json.dumps(item, ensure_ascii=False).lower()
            if kw in blob:
                print(f"[{name}]", json.dumps(item, ensure_ascii=False)[:300])


def cmd_health():
    print(json.dumps(get("/api/health"), ensure_ascii=False, indent=2)[:2000])


def usage():
    print("""usage: gl.py <cmd> [args]

查询: overview|tasks|task|task-qr|task-rfid|drones|shelves|bindings|qr|rfid|inventory|search|health
任务发布: publish-task TASK-001 [name] [drone_id] 01-01,02-01
盘点绑定: bind RFID SKU SHELF | unbind <id> | clear-bindings
二维码:   qr-control [on|off]
数据库:   db tables | db rows TABLE [N] | db export TABLE
RFID:     rfid-status

禁止(AI不可用): start / start-task / takeoff / arm / unlock 等解锁起飞与任务启动
""")


def main():
    if len(sys.argv) < 2:
        usage()
        return
    c = sys.argv[1]
    a = sys.argv[2:]
    guard_forbidden(c, " ".join(a))

    if c == "overview":
        cmd_overview()
    elif c == "tasks":
        cmd_tasks(a[0] if a else 5)
    elif c == "task":
        cmd_task(a[0] if a else "")
    elif c == "task-qr":
        cmd_task_qr(a[0] if a else "")
    elif c == "task-rfid":
        cmd_task_rfid(a[0] if a else "")
    elif c == "drones":
        cmd_drones()
    elif c == "shelves":
        cmd_shelves()
    elif c == "bindings":
        cmd_bindings()
    elif c == "qr":
        cmd_qr(a[0] if a else 10)
    elif c == "rfid":
        cmd_rfid(a[0] if a else 10)
    elif c == "rfid-status":
        cmd_rfid_status()
    elif c == "inventory":
        cmd_inventory()
    elif c == "search":
        cmd_search(a[0] if a else "")
    elif c == "health":
        cmd_health()
    elif c == "publish-task":
        cmd_publish_task(a)
    elif c == "bind":
        cmd_bind(a)
    elif c == "unbind":
        cmd_unbind(a)
    elif c == "clear-bindings":
        cmd_clear_bindings()
    elif c == "qr-control":
        cmd_qr_control(a)
    elif c == "db":
        cmd_db(a)
    else:
        print("unknown", c)
        usage()


if __name__ == "__main__":
    main()
