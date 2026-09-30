#!/usr/bin/env python3
"""ground-lite one-shot DB/API helper for OpenClaw skill."""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8002"


def get(path):
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode("utf-8", "ignore")[:300]}
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


def cmd_overview():
    drones = get("/api/drones") or []
    tasks = get("/api/tasks") or []
    shelves = get("/api/shelves") or []
    bindings = get("/api/inventory-bindings") or []
    if isinstance(drones, dict):
        drones = drones.get("data") or drones.get("items") or []
    if isinstance(tasks, dict):
        tasks = tasks.get("data") or tasks.get("items") or []
    print("=== 无人机 ===")
    for d in drones[:5]:
        print(f"  #{d.get('id')} {d.get('drone_code')} status={d.get('status')} battery={d.get('battery_level')}")
    print("=== 最近任务 ===")
    for t in tasks[:5]:
        print(f"  {t.get('task_code')} status={t.get('status')} shelves={t.get('shelf_ids')} reason={t.get('status_reason')}")
    print(f"=== 货架 {len(shelves)} 个 / 绑定 {len(bindings)} 条 ===")
    for s in shelves[:10]:
        print(f"  {s.get('shelf_code')} {s.get('shelf_name') or ''}")


def cmd_tasks(n=5):
    tasks = get("/api/tasks") or []
    if isinstance(tasks, dict):
        tasks = tasks.get("data") or []
    for t in tasks[: int(n)]:
        print(f"{t.get('task_code')} | {t.get('status')} | drone={t.get('drone_id')} | {fmt_ts(t.get('updated_at'))} | {t.get('status_reason') or ''}")
        print(f"   shelves: {t.get('shelf_ids')}")


def cmd_task(code):
    tasks = get("/api/tasks") or []
    if isinstance(tasks, dict):
        tasks = tasks.get("data") or []
    for t in tasks:
        if t.get("task_code") == code:
            print(json.dumps(t, ensure_ascii=False, indent=2))
            return
    print("NOT_FOUND", code)


def cmd_task_qr(code):
    data = get(f"/api/tasks/{code}/qr-records")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])


def cmd_task_rfid(code):
    data = get(f"/api/tasks/{code}/rfid-records")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])


def cmd_drones():
    print(json.dumps(get("/api/drones"), ensure_ascii=False, indent=2)[:3000])


def cmd_shelves():
    print(json.dumps(get("/api/shelves"), ensure_ascii=False, indent=2)[:3000])


def cmd_bindings():
    print(json.dumps(get("/api/inventory-bindings"), ensure_ascii=False, indent=2)[:3000])


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


def cmd_inventory():
    bindings = get("/api/inventory-bindings") or []
    qr = get("/api/qr-records") or []
    rfid = get("/api/rfid/records") or []
    if isinstance(bindings, dict):
        bindings = bindings.get("data") or []
    if isinstance(qr, dict):
        qr = qr.get("data") or qr.get("items") or []
    if isinstance(rfid, dict):
        rfid = rfid.get("data") or rfid.get("items") or []

    bind_map = {}
    for b in bindings:
        bind_map.setdefault(b.get("sku") or b.get("rfid"), b)

    qr_skus = []
    for q in qr:
        t = q.get("text") or q.get("sku") or ""
        if t:
            qr_skus.append(t)
    rfid_ids = []
    for r in rfid:
        rid = r.get("rfid") or r.get("epc") or ""
        if rid:
            rfid_ids.append(rid)

    qr_set, rfid_set = set(qr_skus), set(rfid_ids)
    bind_skus = {b.get("sku") for b in bindings if b.get("sku")}
    bind_rfids = {b.get("rfid") for b in bindings if b.get("rfid")}

    correct, wrong_shelf, missing, extra = [], [], [], []

    # simple judge by sku
    shelf_of = {}
    for q in qr:
        sku = q.get("text") or ""
        shelf = q.get("shelf_code") or ""
        if not sku:
            continue
        b = bind_map.get(sku)
        if not b:
            if sku not in bind_skus:
                extra.append((sku, shelf, "未绑定"))
                continue
        b_shelf = (b or {}).get("shelf_code")
        if b_shelf and shelf and b_shelf != shelf:
            wrong_shelf.append((sku, shelf, b_shelf))
        elif b_shelf:
            correct.append((sku, shelf))
        else:
            correct.append((sku, shelf))

    for sku in bind_skus:
        if sku not in qr_set and sku not in rfid_set:
            missing.append(sku)

    print("=== 盘点判定 ===")
    print(f"正确: {len(correct)}")
    for x in correct[:20]:
        print("  OK", x)
    print(f"放错: {len(wrong_shelf)}")
    for x in wrong_shelf[:20]:
        print("  WRONG", x)
    print(f"疑似缺失/漏扫: {len(missing)}")
    for x in missing[:20]:
        print("  MISS", x)
    print(f"多出/未绑定: {len(extra)}")
    for x in extra[:20]:
        print("  EXTRA", x)


def cmd_search(kw):
    kw = kw.lower()
    tasks = get("/api/tasks") or []
    shelves = get("/api/shelves") or []
    bindings = get("/api/inventory-bindings") or []
    for coll, name in ((tasks, "task"), (shelves, "shelf"), (bindings, "binding")):
        if isinstance(coll, dict):
            coll = coll.get("data") or []
        for item in coll:
            blob = json.dumps(item, ensure_ascii=False).lower()
            if kw in blob:
                print(f"[{name}]", json.dumps(item, ensure_ascii=False)[:300])


def cmd_health():
    print(json.dumps(get("/api/health"), ensure_ascii=False, indent=2)[:2000])


def main():
    if len(sys.argv) < 2:
        print("usage: gl.py overview|tasks|task|task-qr|task-rfid|drones|shelves|bindings|qr|rfid|inventory|search|health")
        return
    c = sys.argv[1]
    a = sys.argv[2] if len(sys.argv) > 2 else None
    if c == "overview":
        cmd_overview()
    elif c == "tasks":
        cmd_tasks(a or 5)
    elif c == "task":
        cmd_task(a)
    elif c == "task-qr":
        cmd_task_qr(a)
    elif c == "task-rfid":
        cmd_task_rfid(a)
    elif c == "drones":
        cmd_drones()
    elif c == "shelves":
        cmd_shelves()
    elif c == "bindings":
        cmd_bindings()
    elif c == "qr":
        cmd_qr(a or 10)
    elif c == "rfid":
        cmd_rfid(a or 10)
    elif c == "inventory":
        cmd_inventory()
    elif c == "search":
        cmd_search(a or "")
    elif c == "health":
        cmd_health()
    else:
        print("unknown", c)


if __name__ == "__main__":
    main()
