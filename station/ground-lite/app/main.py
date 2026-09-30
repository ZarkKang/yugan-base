import asyncio

import csv

import io

import json

import glob

import logging

import os

import sqlite3

import threading

import time

from pathlib import Path

from typing import Any, Dict, List, Optional

try:
    import serial
except Exception:  # pyserial is optional until RFID is enabled.
    serial = None



import cv2

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse, JSONResponse, Response

from fastapi.staticfiles import StaticFiles



logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

logger = logging.getLogger("ground-lite")



DB_PATH = os.environ.get("GROUND_LITE_DB", "/data/ground-lite.db")

VIDEO_ENABLED = os.environ.get("GROUND_LITE_VIDEO_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

VIDEO_DRONE_ID = int(os.environ.get("GROUND_LITE_DRONE_ID", "1"))
DRONE_OFFLINE_AFTER_SECONDS = float(os.environ.get("GROUND_LITE_DRONE_OFFLINE_AFTER", "15"))
DRONE_COMPLETED_DISPLAY_SECONDS = float(os.environ.get("GROUND_LITE_DRONE_COMPLETED_DISPLAY_SECONDS", "60"))
MISSION_START_TIMEOUT_SECONDS = float(os.environ.get("GROUND_LITE_MISSION_START_TIMEOUT", "60"))
MISSION_TIMEOUT_SECONDS = float(os.environ.get("GROUND_LITE_MISSION_TIMEOUT", "600"))
TASK_SWEEP_INTERVAL_SECONDS = float(os.environ.get("GROUND_LITE_TASK_SWEEP_INTERVAL", "15"))

UDP_SOURCE = os.environ.get(
    "GROUND_LITE_UDP_SOURCE",
    "udp://@:5600?fifo_size=1048576&overrun_nonfatal=1&buffer_size=1048576",
)
VIDEO_REOPEN_AFTER_SECONDS = float(os.environ.get("GROUND_LITE_VIDEO_REOPEN_AFTER", "8"))
VIDEO_REOPEN_MIN_INTERVAL_SECONDS = float(os.environ.get("GROUND_LITE_VIDEO_REOPEN_MIN_INTERVAL", "3"))
VIDEO_REOPEN_MAX_DELAY_SECONDS = float(os.environ.get("GROUND_LITE_VIDEO_REOPEN_MAX_DELAY", "10"))


PREVIEW_FPS = float(os.environ.get("GROUND_LITE_PREVIEW_FPS", "15"))

JPEG_QUALITY = int(os.environ.get("GROUND_LITE_JPEG_QUALITY", "82"))
QR_PROCESS_FPS = float(os.environ.get("GROUND_LITE_QR_PROCESS_FPS", "2"))

QR_CONFIRM_COUNT = max(1, int(os.environ.get("GROUND_LITE_QR_CONFIRM_COUNT", "2")))

QR_SCAN_WIDTH = int(os.environ.get("GROUND_LITE_QR_SCAN_WIDTH", "960"))
QR_ENGINE = os.environ.get("GROUND_LITE_QR_ENGINE", "hybrid").lower()
QR_DETECTION_DEFAULT = os.environ.get("GROUND_LITE_QR_DETECTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
VIDEO_WS_MAX_PER_STREAM = max(1, int(os.environ.get("GROUND_LITE_VIDEO_WS_MAX_PER_STREAM", "2")))
VIDEO_WS_SEND_INTERVAL = float(os.environ.get("GROUND_LITE_VIDEO_WS_SEND_INTERVAL", "0.05"))
RFID_DEFAULT_PORT = os.environ.get("GROUND_LITE_RFID_PORT", "/dev/ttyUSB0")
RFID_BAUDRATE = int(os.environ.get("GROUND_LITE_RFID_BAUDRATE", "115200"))
RFID_SAFE_POWER_DBM = int(os.environ.get("GROUND_LITE_RFID_SAFE_POWER_DBM", "12"))
RFID_MAX_POWER_DBM = int(os.environ.get("GROUND_LITE_RFID_MAX_POWER_DBM", "15"))
RFID_SCAN_MAX_SECONDS = float(os.environ.get("GROUND_LITE_RFID_SCAN_MAX_SECONDS", "5"))

STATIC_DIR = Path(__file__).resolve().parent / "static"
TASK_DATA_DIR = Path(os.environ.get("GROUND_LITE_TASK_DATA_DIR", "/data/tasks"))





def db_conn() -> sqlite3.Connection:

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    conn.row_factory = sqlite3.Row

    return conn





def init_db() -> None:

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with db_conn() as conn:

        conn.executescript(

            """

            create table if not exists drones (

                id integer primary key,

                drone_code text unique not null,

                name text,

                status text default 'offline',

                battery_level real,

                position_x real,

                position_y real,

                position_z real,

                last_seen real,

                created_at real default (strftime('%s','now')),

                updated_at real default (strftime('%s','now'))

            );



            create table if not exists shelves (

                id integer primary key autoincrement,

                shelf_code text not null,

                shelf_name text,

                position_x real,

                position_y real,

                position_z real,

                yaw_rad real,

                arrival_radius_m real,

                dwell_time_s real,

                status text default 'normal',

                last_synced_at real,

                created_at real default (strftime('%s','now')),

                updated_at real default (strftime('%s','now'))

            );

            create unique index if not exists idx_shelves_code on shelves(shelf_code);



            create table if not exists inventory_bindings (
                id integer primary key autoincrement,
                rfid text not null,
                sku text not null,
                shelf_code text not null,
                created_at real default (strftime('%s','now')),
                updated_at real default (strftime('%s','now'))
            );
            create unique index if not exists idx_inventory_bindings_rfid on inventory_bindings(rfid);
            create unique index if not exists idx_inventory_bindings_sku on inventory_bindings(sku);
            create index if not exists idx_inventory_bindings_shelf on inventory_bindings(shelf_code);

            create table if not exists rfid_scan_sessions (
                id integer primary key autoincrement,
                mode text not null,
                task_code text,
                status text default 'created',
                started_at real default (strftime('%s','now')),
                stopped_at real,
                error text
            );

            create table if not exists rfid_scan_records (
                id integer primary key autoincrement,
                session_id integer,
                task_code text,
                rfid text not null,
                epc text not null,
                rssi integer,
                pc text,
                read_count integer default 1,
                first_seen_at real default (strftime('%s','now')),
                last_seen_at real default (strftime('%s','now')),
                shelf_code text,
                match_status text,
                note text
            );
            create index if not exists idx_rfid_scan_records_epc on rfid_scan_records(epc);
            create index if not exists idx_rfid_scan_records_task on rfid_scan_records(task_code);

            create table if not exists qr_records (
                id integer primary key autoincrement,
                drone_id integer,
                text text,
                type text,
                bbox_x integer,
                bbox_y integer,
                bbox_w integer,
                bbox_h integer,
                frame_time real,
                task_code text,
                shelf_code text,
                waypoint_id text,
                waypoint_index integer,
                valid integer default 0,
                session_id text,
                first_seen_at real,
                confirm_count integer default 1,
                created_at real default (strftime('%s','now'))
            );

            create table if not exists inspection_tasks (
                task_code text primary key,
                drone_id integer not null,
                name text,
                status text default 'draft',
                created_at real default (strftime('%s','now')),
                updated_at real default (strftime('%s','now')),
                published_at real,
                started_at real,
                completed_at real
            );

            create table if not exists inspection_task_shelves (
                id integer primary key autoincrement,
                task_code text not null,
                sort_order integer not null,
                shelf_code text not null,
                created_at real default (strftime('%s','now')),
                unique(task_code, shelf_code),
                unique(task_code, sort_order)
            );

            create table if not exists drone_commands (
                id integer primary key autoincrement,
                drone_id integer not null,
                task_code text,
                command text not null,
                payload_json text,
                status text default 'pending',
                created_at real default (strftime('%s','now')),
                consumed_at real
            );

            create table if not exists drone_task_context (
                drone_id integer primary key,
                task_code text,
                shelf_code text,
                waypoint_id text,
                waypoint_index integer,
                status text,
                updated_at real default (strftime('%s','now'))
            );

            """

        )
        cols = {row["name"] for row in conn.execute("pragma table_info(qr_records)").fetchall()}

        if "session_id" not in cols:

            conn.execute("alter table qr_records add column session_id text")

        if "first_seen_at" not in cols:

            conn.execute("alter table qr_records add column first_seen_at real")

        if "confirm_count" not in cols:
            conn.execute("alter table qr_records add column confirm_count integer default 1")
        if "task_code" not in cols:
            conn.execute("alter table qr_records add column task_code text")
        if "valid" not in cols:
            conn.execute("alter table qr_records add column valid integer default 0")
        if "shelf_code" not in cols:
            conn.execute("alter table qr_records add column shelf_code text")
        if "waypoint_id" not in cols:
            conn.execute("alter table qr_records add column waypoint_id text")
        if "waypoint_index" not in cols:
            conn.execute("alter table qr_records add column waypoint_index integer")

        task_cols = {row["name"] for row in conn.execute("pragma table_info(inspection_tasks)").fetchall()}
        task_columns = {
            "execution_phase": "text default ''",
            "last_mission_update_at": "real",
            "last_progress_at": "real",
            "failed_at": "real",
            "aborted_at": "real",
            "status_reason": "text",
        }
        for column, definition in task_columns.items():
            if column not in task_cols:
                conn.execute(f"alter table inspection_tasks add column {column} {definition}")
        conn.execute(
            "create unique index if not exists idx_qr_records_session_drone_text "
            "on qr_records(session_id, drone_id, text)"
        )
        conn.execute("drop index if exists idx_qr_records_task_drone_text")
        conn.execute(
            "create unique index if not exists idx_qr_records_task_context_text "
            "on qr_records(task_code, drone_id, shelf_code, waypoint_id, text)"
        )
        conn.execute(
            "create index if not exists idx_qr_records_task_shelf "
            "on qr_records(task_code, shelf_code, waypoint_id)"
        )

        conn.execute(
            "insert or ignore into drones(id, drone_code, name, status, battery_level) values (?, ?, ?, ?, ?)",
            (VIDEO_DRONE_ID, "DRONE001", "测试无人机", "offline", 100),
        )

        conn.commit()





def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:

    return dict(row)


def normalize_drone_status(status: Any) -> str:
    value = str(status or "online").strip().lower()
    if value in {"online", "ready", "starting", "running", "error"}:
        return value
    if value in {"completed", "stopped", "aborted", "cancelled"}:
        return "online"
    if value in {"failed", "failure"}:
        return "error"
    if value in {"idle", "available"}:
        return "online"
    if value in {"busy", "flying"}:
        return "running"
    if value == "offline":
        return "offline"
    return "online"


def drone_status_from_mission_status(status: str) -> str:
    if status in {"starting", "running", "error"}:
        return status
    return "online"


def drone_display_status(data: Dict[str, Any], conn: sqlite3.Connection | None = None) -> str:
    raw_status = str(data.get("raw_status") or data.get("status") or "offline").lower()
    effective_status = str(data.get("effective_status") or raw_status).lower()
    now = time.time()
    if effective_status == "offline" or raw_status in {"error", "stopped"}:
        return "error"
    if conn is not None:
        active = conn.execute(
            "select task_code from inspection_tasks where drone_id=? and status='running' and execution_phase='running' limit 1",
            (data.get("id"),),
        ).fetchone()
        if active:
            return "busy"
        recent = conn.execute(
            """
            select status, completed_at, failed_at, aborted_at, updated_at
            from inspection_tasks
            where drone_id=? and status in ('completed', 'failed')
            order by coalesce(completed_at, failed_at, aborted_at, updated_at, created_at) desc
            limit 1
            """,
            (data.get("id"),),
        ).fetchone()
        if recent:
            status = str(recent["status"] or "")
            event_at = recent["completed_at"] or recent["failed_at"] or recent["aborted_at"] or recent["updated_at"]
            if event_at and now - float(event_at) <= DRONE_COMPLETED_DISPLAY_SECONDS:
                return "completed" if status == "completed" else "error"
    if raw_status in {"running", "flying", "busy"}:
        return "busy"
    if raw_status in {"failed"}:
        return "error"
    return "online"


def serialize_drone(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    data = row_to_dict(row)
    raw_status = data.get("status") or "offline"
    last_seen = data.get("last_seen")
    now = time.time()
    heartbeat_age = None
    if last_seen:
        heartbeat_age = max(0.0, now - float(last_seen))
    effective_status = raw_status
    if not last_seen or heartbeat_age is None or heartbeat_age > DRONE_OFFLINE_AFTER_SECONDS:
        effective_status = "offline"
    data["raw_status"] = raw_status
    data["effective_status"] = effective_status
    data["display_status"] = drone_display_status(data, conn)
    data["heartbeat_age"] = heartbeat_age
    data["online"] = effective_status not in {"offline", "error", "stopped"}
    data["offline_after"] = DRONE_OFFLINE_AFTER_SECONDS
    return data


class E720RfidService:
    SINGLE_INVENTORY = bytes.fromhex("BB 00 22 00 00 22 7E")
    STOP_INVENTORY = bytes.fromhex("BB 00 28 00 00 28 7E")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ser = None
        self.port = RFID_DEFAULT_PORT
        self.baudrate = RFID_BAUDRATE
        self.power_dbm = None
        self.last_error = None
        self.last_seen = None
        self.last_epc = None

    def ports(self) -> List[str]:
        found = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
        if self.port and self.port not in found:
            found.insert(0, self.port)
        return found

    def is_connected(self) -> bool:
        return bool(self.ser and getattr(self.ser, "is_open", False))

    def status(self) -> Dict[str, Any]:
        return {
            "available": serial is not None,
            "connected": self.is_connected(),
            "port": self.port,
            "ports": self.ports(),
            "baudrate": self.baudrate,
            "safe_power_dbm": RFID_SAFE_POWER_DBM,
            "max_power_dbm": RFID_MAX_POWER_DBM,
            "power_dbm": self.power_dbm,
            "last_error": self.last_error,
            "last_seen": self.last_seen,
            "last_epc": self.last_epc,
        }

    def connect(self, port: Optional[str] = None, baudrate: Optional[int] = None, power_dbm: Optional[int] = None) -> Dict[str, Any]:
        if serial is None:
            raise RuntimeError("pyserial not available")
        with self.lock:
            self.close_locked()
            self.port = port or self.port or RFID_DEFAULT_PORT
            self.baudrate = int(baudrate or self.baudrate or RFID_BAUDRATE)
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.25, write_timeout=0.5)
            self.last_error = None
            # Set a conservative power after opening. This does not start inventory.
            self.set_power_locked(power_dbm or RFID_SAFE_POWER_DBM)
            return self.status()

    def disconnect(self) -> Dict[str, Any]:
        with self.lock:
            self.stop_locked()
            self.close_locked()
            return self.status()

    def close_locked(self) -> None:
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def frame(self, cmd: int, payload: bytes = b"") -> bytes:
        body = bytes([0x00, cmd]) + len(payload).to_bytes(2, "big") + payload
        checksum = sum(body) & 0xFF
        return b"\xBB" + body + bytes([checksum, 0x7E])

    def write_locked(self, data: bytes) -> None:
        if not self.is_connected():
            raise RuntimeError("RFID reader not connected")
        self.ser.reset_input_buffer()
        self.ser.write(data)
        self.ser.flush()

    def read_frame_locked(self, deadline: float) -> Optional[bytes]:
        buf = bytearray()
        while time.time() < deadline:
            chunk = self.ser.read(1)
            if not chunk:
                continue
            b = chunk[0]
            if not buf and b != 0xBB:
                continue
            buf.append(b)
            if b == 0x7E and len(buf) >= 7:
                return bytes(buf)
        return None

    def set_power_locked(self, dbm: int) -> None:
        dbm = max(1, min(int(dbm), RFID_MAX_POWER_DBM))
        value = int(dbm * 100)
        payload = value.to_bytes(2, "big")
        self.write_locked(self.frame(0xB6, payload))
        self.read_frame_locked(time.time() + 0.8)
        self.power_dbm = dbm

    def stop_locked(self) -> None:
        if self.is_connected():
            try:
                self.ser.write(self.STOP_INVENTORY)
                self.ser.flush()
                self.read_frame_locked(time.time() + 0.5)
            except Exception:
                pass

    def parse_inventory(self, frame: bytes) -> Optional[Dict[str, Any]]:
        if len(frame) < 8 or frame[0] != 0xBB or frame[-1] != 0x7E:
            return None
        frame_type, cmd = frame[1], frame[2]
        length = int.from_bytes(frame[3:5], "big")
        payload = frame[5:5 + length]
        if frame_type == 0x01 and cmd == 0xFF:
            self.last_error = f"reader returned error/no tag: 0x{payload[0]:02X}" if payload else "reader returned error/no tag"
            return None
        if cmd != 0x22 or length < 6:
            return None
        rssi = int.from_bytes(payload[0:1], "big", signed=True)
        pc = payload[1:3].hex().upper()
        epc = payload[3:-2].hex().upper()
        if not epc:
            return None
        now = time.time()
        self.last_seen = now
        self.last_epc = epc
        self.last_error = None
        return {"rfid": epc, "epc": epc, "rssi": rssi, "pc": pc, "seen_at": now}

    def scan_once(self) -> Dict[str, Any]:
        with self.lock:
            if not self.is_connected():
                self.connect()
            for _ in range(3):
                self.write_locked(self.SINGLE_INVENTORY)
                deadline = time.time() + 0.8
                while time.time() < deadline:
                    frame = self.read_frame_locked(deadline)
                    if not frame:
                        break
                    parsed = self.parse_inventory(frame)
                    if parsed:
                        return parsed
                time.sleep(0.12)
            raise RuntimeError(self.last_error or "no RFID tag detected")

    def scan_window(self, duration: float) -> List[Dict[str, Any]]:
        duration = max(0.2, min(float(duration), RFID_SCAN_MAX_SECONDS))
        result: Dict[str, Dict[str, Any]] = {}
        end = time.time() + duration
        with self.lock:
            if not self.is_connected():
                self.connect()
            try:
                while time.time() < end:
                    self.ser.write(self.SINGLE_INVENTORY)
                    self.ser.flush()
                    frame = self.read_frame_locked(min(time.time() + 0.4, end))
                    parsed = self.parse_inventory(frame) if frame else None
                    if parsed:
                        epc = parsed["epc"]
                        if epc in result:
                            result[epc]["read_count"] += 1
                            result[epc]["last_seen_at"] = parsed["seen_at"]
                            result[epc]["rssi"] = parsed["rssi"]
                        else:
                            result[epc] = {**parsed, "read_count": 1, "first_seen_at": parsed["seen_at"], "last_seen_at": parsed["seen_at"]}
            finally:
                self.stop_locked()
        return list(result.values())


rfid_service = E720RfidService()





class FrameStore:

    def __init__(self) -> None:

        self.lock = threading.Lock()

        self.raw_seq: Dict[int, int] = {}

        self.processed_seq: Dict[int, int] = {}

        self.raw: Dict[int, bytes] = {}

        self.processed: Dict[int, bytes] = {}

        self.qr_items: Dict[int, List[Dict[str, Any]]] = {}

        self.updated_at: Dict[int, float] = {}

        self.processed_at: Dict[int, float] = {}

        self.frame_count: Dict[int, int] = {}

        self.latest_qr_source: Dict[int, tuple[np.ndarray, float]] = {}

        self.qr_stop_event = threading.Event()

        self.qr_thread: Optional[threading.Thread] = None
        self.qr_detection_enabled = QR_DETECTION_DEFAULT
        # manual is front-end test only; task is waypoint-controlled and persisted.
        self.qr_detection_mode = "manual" if QR_DETECTION_DEFAULT else "off"

        self.qr_session_id: Optional[str] = f"qr-{int(time.time() * 1000)}" if QR_DETECTION_DEFAULT else None

        self.qr_session_started_at: Optional[float] = time.time() if QR_DETECTION_DEFAULT else None

        self.qr_pending: Dict[int, Dict[str, Dict[str, Any]]] = {}

        self.qr_accepted: Dict[int, Dict[str, Dict[str, Any]]] = {}

        self.qr_scan_count = 0
        self.qr_last_count = 0
        self.qr_last_at: Optional[float] = None
        self.qr_last_error: Optional[str] = None



    def start_qr_worker(self) -> None:

        if self.qr_thread and self.qr_thread.is_alive():

            return

        self.qr_stop_event.clear()

        self.qr_thread = threading.Thread(target=self._qr_worker, name="qr-worker", daemon=True)

        self.qr_thread.start()

        logger.info("QR worker started: fps=%s scan_width=%s", QR_PROCESS_FPS, QR_SCAN_WIDTH)



    def stop_qr_worker(self) -> None:

        self.qr_stop_event.set()

        if self.qr_thread and self.qr_thread.is_alive():

            self.qr_thread.join(timeout=5)



    def set_qr_detection(self, enabled: bool, mode: str = "manual", reset: bool = False) -> Dict[str, Any]:
        with self.lock:
            enabled = bool(enabled)
            mode = "task" if mode == "task" else "manual"
            should_reset = enabled and (
                not self.qr_detection_enabled or self.qr_detection_mode != mode or reset
            )
            if should_reset:
                self.qr_session_id = f"qr-{int(time.time() * 1000)}"
                self.qr_session_started_at = time.time()
                self.qr_pending = {}
                self.qr_accepted = {}
                self.qr_items = {}
                self.qr_scan_count = 0
                self.qr_last_count = 0
                self.qr_last_error = None
            self.qr_detection_enabled = enabled
            self.qr_detection_mode = mode if enabled else "off"
            return self._qr_control_status_unlocked()

    def qr_control_status(self) -> Dict[str, Any]:

        with self.lock:

            return self._qr_control_status_unlocked()



    def _qr_control_status_unlocked(self) -> Dict[str, Any]:

        accepted_count = sum(len(items) for items in self.qr_accepted.values())

        return {

            "enabled": self.qr_detection_enabled,
            "mode": self.qr_detection_mode,

            "engine": QR_ENGINE,

            "process_fps": QR_PROCESS_FPS,

            "confirm_count": QR_CONFIRM_COUNT,

            "session_id": self.qr_session_id,

            "session_started_at": self.qr_session_started_at,

            "accepted_count": accepted_count,

        }



    def _accept_qr_items(self, drone_id: int, items: List[Dict[str, Any]], ts: float) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:

        session_id = self.qr_session_id

        if not session_id:

            return [], [], None

        pending = self.qr_pending.setdefault(drone_id, {})

        accepted = self.qr_accepted.setdefault(drone_id, {})

        newly_accepted: List[Dict[str, Any]] = []

        for item in items:

            text = str(item.get("text") or "").strip()

            if not text or text in accepted:

                continue

            entry = pending.setdefault(text, {"count": 0, "first_seen_at": ts, "item": item})

            entry["count"] = int(entry.get("count") or 0) + 1

            entry["item"] = item

            if entry["count"] >= QR_CONFIRM_COUNT:

                accepted_item = dict(item)

                accepted_item["text"] = text

                accepted_item["first_seen_at"] = entry.get("first_seen_at", ts)

                accepted_item["confirm_count"] = entry["count"]

                accepted_item["session_id"] = session_id

                accepted[text] = accepted_item

                newly_accepted.append(accepted_item)

        accepted_items = sorted(accepted.values(), key=lambda item: item.get("first_seen_at") or 0)

        return accepted_items, newly_accepted, session_id


    def update(self, drone_id: int, frame: np.ndarray) -> None:
        now = time.time()
        raw = self._encode(frame)
        with self.lock:
            self.raw_seq[drone_id] = self.raw_seq.get(drone_id, 0) + 1
            self.raw[drone_id] = raw
            self.updated_at[drone_id] = now
            self.frame_count[drone_id] = self.frame_count.get(drone_id, 0) + 1
            self.latest_qr_source[drone_id] = (frame.copy(), now)
            # Keep the processed stream live even if QR recognition is slower than video input.
            self.processed_seq[drone_id] = self.processed_seq.get(drone_id, 0) + 1
            self.processed[drone_id] = raw
            self.processed_at[drone_id] = now


    def get(self, drone_id: int, mode: str) -> Optional[Dict[str, Any]]:

        with self.lock:

            if mode == "processed":

                frame = self.processed.get(drone_id)

                seq = self.processed_seq.get(drone_id, 0)

                updated_at = self.processed_at.get(drone_id)

            else:

                frame = self.raw.get(drone_id)

                seq = self.raw_seq.get(drone_id, 0)

                updated_at = self.updated_at.get(drone_id)

            if frame is None:

                return None

            return {

                "seq": seq,

                "frame": frame,

                "items": list(self.qr_items.get(drone_id, [])),

                "updated_at": updated_at,

            }



    def list_qr_items(self, limit: int = 80) -> List[Dict[str, Any]]:
        with self.lock:
            rows: List[Dict[str, Any]] = []
            for drone_id, items in self.qr_items.items():
                for item in items:
                    row = dict(item)
                    bbox = row.get("bbox") or {}
                    row.update({
                        "drone_id": drone_id,
                        "bbox_x": bbox.get("x"),
                        "bbox_y": bbox.get("y"),
                        "bbox_w": bbox.get("w"),
                        "bbox_h": bbox.get("h"),
                        "frame_time": row.get("first_seen_at"),
                        "created_at": row.get("first_seen_at"),
                    })
                    rows.append(row)
            rows.sort(key=lambda row: row.get("first_seen_at") or row.get("frame_time") or 0)
            return rows[:limit]


    def status(self) -> Dict[str, Any]:

        with self.lock:

            return {

                "enabled": VIDEO_ENABLED,

                "source": UDP_SOURCE,

                "preview_fps": PREVIEW_FPS,

                "qr_process_fps": QR_PROCESS_FPS,
                "qr_scan_width": QR_SCAN_WIDTH,
                "qr_engine": QR_ENGINE,
                "qr_detection_enabled": self.qr_detection_enabled,
                "qr_detection_mode": self.qr_detection_mode,

                "qr_confirm_count": QR_CONFIRM_COUNT,

                "qr_session_id": self.qr_session_id,

                "qr_accepted_count": sum(len(items) for items in self.qr_accepted.values()),

                "qr_scan_count": self.qr_scan_count,
                "qr_last_count": self.qr_last_count,
                "qr_last_at": self.qr_last_at,
                "qr_last_error": self.qr_last_error,

                "frame_count": dict(self.frame_count),

                "updated_at": dict(self.updated_at),

            }



    def _qr_worker(self) -> None:
        interval = 1.0 / QR_PROCESS_FPS if QR_PROCESS_FPS > 0 else 0.5
        last_seen: Dict[int, float] = {}
        while not self.qr_stop_event.is_set():
            jobs: List[tuple[int, np.ndarray, float]] = []
            with self.lock:
                enabled = self.qr_detection_enabled
                if enabled:
                    for drone_id, (frame, ts) in self.latest_qr_source.items():
                        if ts != last_seen.get(drone_id):
                            last_seen[drone_id] = ts
                            jobs.append((drone_id, frame, ts))
            if not enabled:
                self.qr_stop_event.wait(0.2)
                continue
            for drone_id, frame, ts in jobs:
                try:
                    processed, items = self._process_qr(frame)
                    with self.lock:
                        self.qr_scan_count += 1

                        accepted_items, newly_accepted, session_id = self._accept_qr_items(drone_id, items, ts)

                        self.qr_last_count = len(items)

                        self.qr_last_at = time.time()

                        self.qr_last_error = None

                        self.processed_seq[drone_id] = self.processed_seq.get(drone_id, 0) + 1

                        self.processed[drone_id] = processed

                        self.qr_items[drone_id] = accepted_items

                        self.processed_at[drone_id] = ts

                    with self.lock:
                        task_mode = self.qr_detection_mode == "task"
                    task_code = get_active_task_code(drone_id) if task_mode else ""
                    context = get_drone_task_context(drone_id) if task_code else {}
                    if task_code:
                        with self.lock:
                            for item in self.qr_items.get(drone_id, []):
                                item["task_code"] = task_code
                                item["shelf_code"] = context.get("shelf_code") or ""
                                item["waypoint_id"] = context.get("waypoint_id") or ""
                                item["waypoint_index"] = context.get("waypoint_index")
                            for item in newly_accepted:
                                item["task_code"] = task_code
                                item["shelf_code"] = context.get("shelf_code") or ""
                                item["waypoint_id"] = context.get("waypoint_id") or ""
                                item["waypoint_index"] = context.get("waypoint_index")
                    if newly_accepted and session_id and task_code:
                        save_qr_records(drone_id, newly_accepted, ts, session_id, task_code, context)
                    else:
                        # Manual front-end QR tests have no task_code and stay in memory only.
                        _ = newly_accepted, session_id
                except Exception as exc:
                    with self.lock:
                        self.qr_scan_count += 1
                        self.qr_last_error = str(exc)
                        self.qr_last_at = time.time()
                    logger.warning("QR processing failed: %s", exc, exc_info=True)
            self.qr_stop_event.wait(interval)


    def _encode(self, frame: np.ndarray) -> bytes:

        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])

        if not ok:

            raise RuntimeError("JPEG encode failed")

        return encoded.tobytes()



    def _process_qr(self, frame: np.ndarray) -> tuple[bytes, List[Dict[str, Any]]]:

        out = frame.copy()
        qr_frame = frame
        coord_scale = 1.0
        if QR_SCAN_WIDTH and QR_SCAN_WIDTH > 0 and frame.shape[1] > QR_SCAN_WIDTH:
            coord_scale = frame.shape[1] / float(QR_SCAN_WIDTH)
            qr_height = max(1, int(frame.shape[0] / coord_scale))
            qr_frame = cv2.resize(frame, (QR_SCAN_WIDTH, qr_height), interpolation=cv2.INTER_AREA)

        items: List[Dict[str, Any]] = []

        detections: List[Dict[str, Any]] = []

        seen: set[str] = set()



        def add_detection(text: str, typ: str, pts: list[tuple[int, int]], rect: Any = None) -> None:

            clean_text = str(text or "QR").strip()
            if clean_text and clean_text != "QR":
                key = f"text:{typ or 'QR'}:{clean_text}"
            elif pts:
                xs = [int(p[0]) for p in pts]
                ys = [int(p[1]) for p in pts]
                key = f"pts:{typ or 'QR'}:{min(xs)//20}:{min(ys)//20}:{max(xs)//20}:{max(ys)//20}"
            else:
                key = f"rect:{typ or 'QR'}:{getattr(rect, 'left', '')//20 if rect is not None else ''}:{getattr(rect, 'top', '')//20 if rect is not None else ''}:{getattr(rect, 'width', '')}:{getattr(rect, 'height', '')}"

            if key in seen:

                return

            seen.add(key)

            detections.append({"text": clean_text or "QR", "type": typ or "QR", "points": pts, "rect": rect})



        gray = cv2.cvtColor(qr_frame, cv2.COLOR_BGR2GRAY)

        candidates: List[tuple[str, np.ndarray, float]] = [("gray", gray, 1.0)]

        try:

            candidates.append(("equalized", cv2.equalizeHist(gray), 1.0))

        except Exception:

            pass

        try:

            candidates.append(("adaptive", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 3), 1.0))

        except Exception:

            pass

        # Small distant codes often need more pixels per module.

        for scale_up in (1.5, 2.0):

            try:

                up = cv2.resize(gray, None, fx=scale_up, fy=scale_up, interpolation=cv2.INTER_CUBIC)

                candidates.append((f"up{scale_up}", up, scale_up))

            except Exception:

                pass



        if QR_ENGINE in {"pyzbar", "hybrid"}:

            try:

                from pyzbar.pyzbar import decode as pyzbar_decode

                for _, image, scale in candidates:

                    decoded = pyzbar_decode(image)

                    for barcode in decoded:

                        points = getattr(barcode, "polygon", None) or []

                        pts = [(int((p.x / scale) * coord_scale), int((p.y / scale) * coord_scale)) for p in points]

                        rect = getattr(barcode, "rect", None)

                        if rect is not None:

                            class Rect:

                                pass

                            scaled = Rect()

                            scaled.left = int((rect.left / scale) * coord_scale)

                            scaled.top = int((rect.top / scale) * coord_scale)

                            scaled.width = int((rect.width / scale) * coord_scale)

                            scaled.height = int((rect.height / scale) * coord_scale)

                            rect = scaled

                        try:

                            text = barcode.data.decode("utf-8")

                        except Exception:

                            text = "QR"

                        add_detection(text, getattr(barcode, "type", "QR"), pts, rect)

            except Exception as exc:

                logger.warning("pyzbar QR decode failed: %s", exc)



        if QR_ENGINE in {"opencv", "hybrid"}:

            detector = cv2.QRCodeDetector()

            for _, image, scale in candidates:

                try:

                    ok, decoded, points, _ = detector.detectAndDecodeMulti(image)

                    if ok and points is not None:

                        for text, pts in zip(decoded, points):

                            if text:

                                add_detection(text, "QR", [(int((x / scale) * coord_scale), int((y / scale) * coord_scale)) for x, y in pts])

                except Exception as exc:

                    logger.debug("OpenCV multi QR decode failed: %s", exc)

                try:

                    text, points, _ = detector.detectAndDecode(image)

                    if text and points is not None:

                        add_detection(text, "QR", [(int((x / scale) * coord_scale), int((y / scale) * coord_scale)) for x, y in points.reshape(-1, 2)])

                except Exception as exc:

                    logger.debug("OpenCV QR decode failed: %s", exc)



        for idx, det in enumerate(detections, start=1):

            pts = np.array(det.get("points") or [], dtype=np.int32)

            if len(pts) >= 3:

                x, y, w, h = cv2.boundingRect(pts)

                cv2.polylines(out, [pts], True, (0, 255, 0), 3)

            else:

                rect = det.get("rect")

                if rect is None:

                    continue

                x = int(rect.left)

                y = int(rect.top)

                w = int(rect.width)

                h = int(rect.height)

                cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 3)

            text = det.get("text") or "QR"

            typ = det.get("type") or "QR"

            items.append({"index": idx, "text": text, "type": typ, "bbox": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}})

            label = f"QR{idx}: {text[:48]}"

            label_y = max(22, y - 8)

            (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)

            cv2.rectangle(out, (x, label_y - th - base - 5), (x + tw + 8, label_y + 5), (0, 255, 0), -1)

            cv2.putText(out, label, (x + 4, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2, cv2.LINE_AA)



        if items:

            logger.info("QR detections: drone_id=%s count=%s texts=%s", VIDEO_DRONE_ID, len(items), [item.get("text") for item in items])

        status = f"QR processed | detections: {len(items)} | engine: {QR_ENGINE} | scan_width: {QR_SCAN_WIDTH or frame.shape[1]}"

        cv2.rectangle(out, (10, 10), (520, 48), (0, 0, 0), -1)

        cv2.putText(out, status, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2, cv2.LINE_AA)

        return self._encode(out), items


frame_store = FrameStore()





def get_drone_task_context(drone_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("select * from drone_task_context where drone_id=?", (drone_id,)).fetchone()
        return row_to_dict(row) if row else {}


def set_drone_task_context(
    drone_id: int,
    task_code: str = "",
    shelf_code: str = "",
    waypoint_id: str = "",
    waypoint_index: Optional[int] = None,
    status: str = "",
) -> Dict[str, Any]:
    now = time.time()
    with db_conn() as conn:
        existing = conn.execute("select * from drone_task_context where drone_id=?", (drone_id,)).fetchone()
        task_code = task_code or (existing["task_code"] if existing else "")
        shelf_code = shelf_code or (existing["shelf_code"] if existing else "")
        waypoint_id = waypoint_id or (existing["waypoint_id"] if existing else "")
        if waypoint_index is None and existing:
            waypoint_index = existing["waypoint_index"]
        status = status or (existing["status"] if existing else "")
        conn.execute(
            """
            insert into drone_task_context(drone_id, task_code, shelf_code, waypoint_id, waypoint_index, status, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(drone_id) do update set
                task_code=excluded.task_code,
                shelf_code=excluded.shelf_code,
                waypoint_id=excluded.waypoint_id,
                waypoint_index=excluded.waypoint_index,
                status=excluded.status,
                updated_at=excluded.updated_at
            """,
            (drone_id, task_code, shelf_code, waypoint_id, waypoint_index, status, now),
        )
        conn.commit()
    return get_drone_task_context(drone_id)


def clear_drone_task_context(drone_id: int, task_code: str = "", status: str = "") -> None:
    with db_conn() as conn:
        if task_code:
            conn.execute(
                "update drone_task_context set status=?, updated_at=? where drone_id=? and task_code=?",
                (status or "stopped", time.time(), drone_id, task_code),
            )
        else:
            conn.execute("delete from drone_task_context where drone_id=?", (drone_id,))
        conn.commit()


def resolve_waypoint_context(
    drone_id: int,
    task_code: str,
    waypoint_id: str,
    payload: Dict[str, Any],
    status: str = "arrived",
) -> Dict[str, Any]:
    shelf_code = str(
        payload.get("shelf_code")
        or payload.get("shelf_id")
        or payload.get("shelf")
        or waypoint_id
        or ""
    ).strip()
    waypoint_index = payload.get("waypoint_index") or payload.get("order") or payload.get("index")
    try:
        waypoint_index = int(waypoint_index) if waypoint_index is not None else None
    except Exception:
        waypoint_index = None
    if (not shelf_code or waypoint_index is None) and task_code:
        with db_conn() as conn:
            row = conn.execute(
                """
                select shelf_code, sort_order from inspection_task_shelves
                where task_code=? and (shelf_code=? or sort_order=?)
                order by sort_order limit 1
                """,
                (task_code, waypoint_id, waypoint_index if waypoint_index is not None else -1),
            ).fetchone()
            if row:
                shelf_code = shelf_code or row["shelf_code"]
                waypoint_index = waypoint_index if waypoint_index is not None else row["sort_order"]
    return set_drone_task_context(
        drone_id=drone_id,
        task_code=task_code,
        shelf_code=shelf_code,
        waypoint_id=str(waypoint_id or shelf_code or ""),
        waypoint_index=waypoint_index,
        status=status,
    )


def append_task_qr_files(task_code: str, row: Dict[str, Any]) -> None:
    task_dir = TASK_DATA_DIR / task_code
    task_dir.mkdir(parents=True, exist_ok=True)
    jsonl = task_dir / "qr_records.jsonl"
    with jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    csv_path = task_dir / "qr_records.csv"
    if not csv_path.exists():
        csv_path.write_text(
            "task_code,drone_id,shelf_code,waypoint_id,waypoint_index,text,type,bbox_x,bbox_y,bbox_w,bbox_h,first_seen_at,confirm_count\n",
            encoding="utf-8",
        )
    with csv_path.open("a", encoding="utf-8") as f:
        text = str(row.get("text") or "").replace('"', '""')
        f.write(
            f"{row.get('task_code','')},{row.get('drone_id','')},{row.get('shelf_code','')},{row.get('waypoint_id','')},{row.get('waypoint_index','')},\"{text}\",{row.get('type','')},"
            f"{row.get('bbox_x','')},{row.get('bbox_y','')},{row.get('bbox_w','')},{row.get('bbox_h','')},"
            f"{row.get('first_seen_at','')},{row.get('confirm_count','')}\n"
        )

def save_qr_records(drone_id: int, items: List[Dict[str, Any]], ts: float, session_id: str, task_code: str, context: Optional[Dict[str, Any]] = None) -> None:
    if not task_code:
        return
    context = context or get_drone_task_context(drone_id)
    shelf_code = str(context.get("shelf_code") or "")
    waypoint_id = str(context.get("waypoint_id") or "")
    waypoint_index = context.get("waypoint_index")
    with db_conn() as conn:
        for item in items:
            bbox = item.get("bbox") or {}
            row = {
                "task_code": task_code,
                "drone_id": drone_id,
                "shelf_code": shelf_code,
                "waypoint_id": waypoint_id,
                "waypoint_index": waypoint_index,
                "text": item.get("text"),
                "type": item.get("type"),
                "bbox_x": bbox.get("x"),
                "bbox_y": bbox.get("y"),
                "bbox_w": bbox.get("w"),
                "bbox_h": bbox.get("h"),
                "frame_time": ts,
                "first_seen_at": item.get("first_seen_at", ts),
                "confirm_count": item.get("confirm_count", 1),
            }
            cur = conn.execute(
                """
                insert or ignore into qr_records(
                    session_id, task_code, shelf_code, waypoint_id, waypoint_index, valid, drone_id, text, type, bbox_x, bbox_y, bbox_w, bbox_h,
                    frame_time, first_seen_at, confirm_count
                ) values (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_code,
                    row["shelf_code"],
                    row["waypoint_id"],
                    row["waypoint_index"],
                    drone_id,
                    row["text"],
                    row["type"],
                    row["bbox_x"],
                    row["bbox_y"],
                    row["bbox_w"],
                    row["bbox_h"],
                    row["frame_time"],
                    row["first_seen_at"],
                    row["confirm_count"],
                ),
            )
            if cur.rowcount:
                append_task_qr_files(task_code, row)
        conn.commit()


class UdpVideoReceiver:

    def __init__(self) -> None:

        self.stop_event = threading.Event()

        self.thread: Optional[threading.Thread] = None



    def start(self) -> None:

        if not VIDEO_ENABLED:

            logger.info("UDP video receiver disabled")

            return

        if self.thread and self.thread.is_alive():

            return

        self.stop_event.clear()

        self.thread = threading.Thread(target=self._run, name="udp-video-receiver", daemon=True)

        self.thread.start()

        logger.info("UDP video receiver started: %s", UDP_SOURCE)



    def stop(self) -> None:

        self.stop_event.set()

        if self.thread and self.thread.is_alive():

            self.thread.join(timeout=5)



    def _run(self) -> None:

        min_interval = 1.0 / PREVIEW_FPS if PREVIEW_FPS > 0 else 0

        reopen_delay = 2.0

        last_open_attempt = 0.0

        while not self.stop_event.is_set():

            cap = None

            try:

                now = time.time()

                wait_before_open = VIDEO_REOPEN_MIN_INTERVAL_SECONDS - (now - last_open_attempt)

                if wait_before_open > 0:

                    self.stop_event.wait(wait_before_open)

                    if self.stop_event.is_set():

                        break

                last_open_attempt = time.time()

                logger.info("opening video source: %s", UDP_SOURCE)

                os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "fflags;nobuffer|flags;low_delay|avioflags;direct|flush_packets;1|max_delay;200000|reorder_queue_size;0|probesize;65536|analyzeduration;0")
                cap = cv2.VideoCapture(UDP_SOURCE, cv2.CAP_FFMPEG)

                try:

                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                except Exception:

                    pass

                if not cap.isOpened():

                    logger.warning("video source open failed")

                    time.sleep(reopen_delay)

                    continue

                logger.info("video source opened")

                last_sent = 0.0

                last_frame_at = time.time()

                count = 0

                while not self.stop_event.is_set():

                    ok, frame = cap.read()

                    now = time.time()

                    if not ok or frame is None:

                        if now - last_frame_at > VIDEO_REOPEN_AFTER_SECONDS:

                            logger.warning("no video frame for %.1fs, reopening", VIDEO_REOPEN_AFTER_SECONDS)

                            reopen_delay = min(VIDEO_REOPEN_MAX_DELAY_SECONDS, max(2.0, reopen_delay * 1.5))

                            break

                        time.sleep(0.05)

                        continue

                    last_frame_at = now

                    if min_interval and now - last_sent < min_interval:

                        continue

                    last_sent = now

                    frame_store.update(VIDEO_DRONE_ID, frame)

                    count += 1

                    if count == 1:

                        reopen_delay = 2.0

                    if count == 1 or count % 100 == 0:

                        logger.info("video frames received: drone_id=%s count=%s", VIDEO_DRONE_ID, count)

            except Exception as exc:

                logger.warning("video receiver error: %s", exc, exc_info=True)

                reopen_delay = min(VIDEO_REOPEN_MAX_DELAY_SECONDS, max(2.0, reopen_delay * 1.5))

                self.stop_event.wait(reopen_delay)

            finally:

                if cap is not None:

                    try:

                        cap.release()

                    except Exception:

                        pass

                if not self.stop_event.is_set():

                    self.stop_event.wait(reopen_delay)





receiver = UdpVideoReceiver()

app = FastAPI(title="Ground Lite", version="0.1.0")
video_ws_clients: Dict[tuple[int, str], List[WebSocket]] = {}
video_ws_lock = asyncio.Lock()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from app.ai_chat import router as ai_chat_router
app.include_router(ai_chat_router)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")





@app.on_event("startup")

def on_startup() -> None:

    global task_sweeper_thread

    init_db()

    migrate_legacy_task_statuses()
    reconcile_task_states()
    ensure_task_indexes()
    task_sweeper_stop.clear()
    task_sweeper_thread = threading.Thread(target=task_sweeper_loop, name="task-timeout-sweeper", daemon=True)
    task_sweeper_thread.start()

    frame_store.start_qr_worker()

    receiver.start()





@app.on_event("shutdown")

def on_shutdown() -> None:

    task_sweeper_stop.set()
    if task_sweeper_thread and task_sweeper_thread.is_alive():
        task_sweeper_thread.join(timeout=2.0)

    receiver.stop()
    frame_store.stop_qr_worker()





@app.get("/")

def index() -> FileResponse:

    return FileResponse(STATIC_DIR / "index.html")





@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "db": DB_PATH, "video": frame_store.status()}


@app.get("/api/qr-control")
def get_qr_control() -> Dict[str, Any]:
    return {"success": True, "data": frame_store.qr_control_status()}


@app.post("/api/qr-control")
async def set_qr_control(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    enabled = bool(payload.get("enabled"))
    current = frame_store.qr_control_status()
    if current.get("mode") == "task":
        return JSONResponse(
            {"success": False, "detail": "Task QR inspection is controlled by waypoint events"},
            status_code=409,
        )
    return {"success": True, "data": frame_store.set_qr_detection(enabled, mode="manual")}

@app.get("/api/drones")

def list_drones() -> List[Dict[str, Any]]:

    with db_conn() as conn:

        rows = conn.execute("select * from drones order by id").fetchall()

        return [serialize_drone(r, conn) for r in rows]





@app.get("/api/drones/{drone_id}")

def get_drone(drone_id: int) -> Dict[str, Any]:

    with db_conn() as conn:

        row = conn.execute("select * from drones where id=?", (drone_id,)).fetchone()

        if not row:

            return JSONResponse({"detail": "drone not found"}, status_code=404)

        return serialize_drone(row, conn)





@app.post("/api/drones/{drone_id}/heartbeat")

async def heartbeat(drone_id: int, request: Request) -> Dict[str, Any]:

    payload = await request.json()

    client_ip = request.client.host if request.client else ""
    update_drone_from_payload(drone_id, payload, client_ip=client_ip)

    return {"success": True, "message": "heartbeat received", "data": {"drone_id": drone_id, "server_time": time.time()}}





@app.post("/api/drones/{drone_id}/shelves/sync")

async def shelves_sync(drone_id: int, request: Request) -> Dict[str, Any]:

    payload = await request.json()

    update_drone_from_payload(drone_id, payload)

    shelves = payload.get("shelves") or payload.get("data", {}).get("shelves") or []

    synced = 0

    now = time.time()

    with db_conn() as conn:

        for shelf in shelves:

            code = str(shelf.get("shelf_code") or shelf.get("shelf_id") or shelf.get("id") or shelf.get("code") or "").strip()

            if not code:

                continue

            pos = shelf.get("position") or {}

            x = shelf.get("position_x", pos.get("x"))

            y = shelf.get("position_y", pos.get("y"))

            z = shelf.get("position_z", pos.get("z"))

            conn.execute(

                """

                insert into shelves(shelf_code, shelf_name, position_x, position_y, position_z, yaw_rad, arrival_radius_m, dwell_time_s, status, last_synced_at, updated_at)

                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                on conflict(shelf_code) do update set

                    shelf_name=excluded.shelf_name,

                    position_x=excluded.position_x,

                    position_y=excluded.position_y,

                    position_z=excluded.position_z,

                    yaw_rad=excluded.yaw_rad,

                    arrival_radius_m=excluded.arrival_radius_m,

                    dwell_time_s=excluded.dwell_time_s,

                    status=excluded.status,

                    last_synced_at=excluded.last_synced_at,

                    updated_at=excluded.updated_at

                """,

                (code, shelf.get("shelf_name") or shelf.get("name") or code, x, y, z, shelf.get("yaw_rad"), shelf.get("arrival_radius_m"), shelf.get("dwell_time_s"), shelf.get("status") or "normal", now, now),

            )

            synced += 1

        conn.commit()

    return {"success": True, "message": "shelves synced", "data": {"drone_id": drone_id, "synced": synced}}





def update_drone_from_payload(drone_id: int, payload: Dict[str, Any], client_ip: str = "") -> None:

    now = time.time()

    code = payload.get("drone_code") or payload.get("code") or f"DRONE{drone_id:03d}"

    name = payload.get("drone_name") or payload.get("name") or code

    battery = payload.get("battery") if payload.get("battery") is not None else payload.get("battery_level")

    raw_status = str(payload.get("status") or "online").strip().lower()
    status = normalize_drone_status(raw_status)

    pos = payload.get("position") or {}

    x = payload.get("position_x", pos.get("x"))

    y = payload.get("position_y", pos.get("y"))

    z = payload.get("position_z", pos.get("z"))

    ts = payload.get("timestamp") or now

    with db_conn() as conn:
        previous = conn.execute("select status from drones where id=?", (drone_id,)).fetchone()

        conn.execute(

            """

            insert into drones(id, drone_code, name, status, battery_level, position_x, position_y, position_z, last_seen, updated_at)

            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            on conflict(id) do update set

                drone_code=excluded.drone_code,

                name=excluded.name,

                status=excluded.status,

                battery_level=coalesce(excluded.battery_level, drones.battery_level),

                position_x=coalesce(excluded.position_x, drones.position_x),

                position_y=coalesce(excluded.position_y, drones.position_y),

                position_z=coalesce(excluded.position_z, drones.position_z),

                last_seen=excluded.last_seen,

                updated_at=excluded.updated_at

            """,

            (drone_id, code, name, status, battery, x, y, z, ts, now),

        )

        conn.commit()
    old_status = str(previous["status"] or "") if previous else ""
    if old_status != status or raw_status != status:
        logger.info(
            "drone heartbeat status drone_id=%s client_ip=%s old_status=%s raw_status=%s normalized_status=%s navigation_ready=%s navigation_message=%s timestamp=%.3f",
            drone_id, client_ip, old_status, raw_status, status,
            payload.get("navigation_ready"), str(payload.get("navigation_message") or ""), now,
        )







def normalize_task_code(value: Any) -> str:
    return str(value or "").strip()


TERMINAL_TASK_STATUSES = {"completed", "failed", "aborted", "cancelled"}
ACTIVE_TASK_STATUSES = {"running"}
task_sweeper_stop = threading.Event()
task_sweeper_thread: Optional[threading.Thread] = None


def task_state_label(status: str, phase: str = "") -> str:
    return f"{status}({phase})" if phase else status


def transition_task(
    conn: sqlite3.Connection,
    task_code: str,
    new_status: str,
    reason: str,
    *,
    new_phase: str = "",
    now: Optional[float] = None,
) -> bool:
    """Apply one task transition and all terminal timestamps in the caller transaction."""
    now = now or time.time()
    row = conn.execute(
        "select task_code, drone_id, status, execution_phase from inspection_tasks where task_code=?",
        (task_code,),
    ).fetchone()
    if not row:
        return False
    old_status = str(row["status"] or "")
    old_phase = str(row["execution_phase"] or "")
    if old_status in TERMINAL_TASK_STATUSES and new_status not in TERMINAL_TASK_STATUSES:
        logger.warning(
            "task transition ignored drone_id=%s task_code=%s old_status=%s new_status=%s reason=%s timestamp=%.3f",
            row["drone_id"], task_code, task_state_label(old_status, old_phase),
            task_state_label(new_status, new_phase), "terminal task cannot be resurrected", now,
        )
        return False
    terminal_at = now if new_status in TERMINAL_TASK_STATUSES else None
    conn.execute(
        """
        update inspection_tasks
        set status=?, execution_phase=?, updated_at=?, status_reason=?,
            completed_at=case when ? is not null then coalesce(completed_at, ?) else completed_at end,
            failed_at=case when ?='failed' then coalesce(failed_at, ?) else failed_at end,
            aborted_at=case when ?='aborted' then coalesce(aborted_at, ?) else aborted_at end
        where task_code=?
        """,
        (
            new_status, new_phase, now, reason,
            terminal_at, terminal_at, new_status, now, new_status, now, task_code,
        ),
    )
    context_status = new_phase or new_status
    conn.execute(
        "update drone_task_context set status=?, updated_at=? where drone_id=? and task_code=?",
        (context_status, now, row["drone_id"], task_code),
    )
    if old_status != new_status or old_phase != new_phase:
        logger.info(
            "task status changed drone_id=%s task_code=%s old_status=%s new_status=%s reason=%s timestamp=%.3f",
            row["drone_id"], task_code, task_state_label(old_status, old_phase),
            task_state_label(new_status, new_phase), reason, now,
        )
    return True


def mark_task_progress(task_code: str, reason: str, now: Optional[float] = None) -> None:
    if not task_code:
        return
    now = now or time.time()
    with db_conn() as conn:
        conn.execute(
            """
            update inspection_tasks
            set last_progress_at=?, updated_at=?, status_reason=?
            where task_code=? and status='running'
            """,
            (now, now, reason, task_code),
        )
        conn.commit()


def migrate_legacy_task_statuses() -> None:
    mappings = {"draft": "pending", "error": "failed", "stopped": "aborted", "stop_requested": "running"}
    with db_conn() as conn:
        for old_status, new_status in mappings.items():
            rows = conn.execute(
                "select task_code from inspection_tasks where status=?", (old_status,)
            ).fetchall()
            for row in rows:
                phase = "stop_requested" if old_status == "stop_requested" else ""
                transition_task(conn, row["task_code"], new_status, f"migrated legacy status {old_status}", new_phase=phase)
        rows = conn.execute(
            "select task_code from inspection_tasks where status in ('start_requested', 'starting')"
        ).fetchall()
        for row in rows:
            transition_task(conn, row["task_code"], "running", "migrated legacy starting task", new_phase="starting")
        completed = conn.execute(
            "select task_code from inspection_tasks where status='completed' and completed_at is null"
        ).fetchall()
        for row in completed:
            transition_task(conn, row["task_code"], "completed", "backfilled terminal timestamp")
        conn.commit()


def reconcile_task_states(drone_id: Optional[int] = None) -> int:
    """Abort timed-out or duplicate active tasks and return the number reclaimed."""
    now = time.time()
    reclaimed = 0
    with db_conn() as conn:
        params: List[Any] = []
        drone_filter = ""
        if drone_id is not None:
            drone_filter = " and drone_id=?"
            params.append(drone_id)
        rows = conn.execute(
            """
            select task_code, drone_id, execution_phase,
                   coalesce(last_mission_update_at, last_progress_at, started_at, updated_at) as activity_at
            from inspection_tasks where status='running'
            """ + drone_filter,
            params,
        ).fetchall()
        for row in rows:
            phase = str(row["execution_phase"] or "running")
            activity_at = float(row["activity_at"] or 0)
            timeout = MISSION_START_TIMEOUT_SECONDS if phase in {"starting", "dispatching"} else MISSION_TIMEOUT_SECONDS
            if now - activity_at > timeout:
                reason = f"{phase} timeout: no mission progress for {int(now - activity_at)}s (limit {int(timeout)}s)"
                if transition_task(conn, row["task_code"], "aborted", reason, now=now):
                    reclaimed += 1

        duplicate_rows = conn.execute(
            """
            select drone_id from inspection_tasks where status='running'
            group by drone_id having count(*) > 1
            """,
        ).fetchall()
        for duplicate in duplicate_rows:
            dup_drone_id = int(duplicate["drone_id"])
            if drone_id is not None and dup_drone_id != drone_id:
                continue
            active = conn.execute(
                """
                select task_code from inspection_tasks where drone_id=? and status='running'
                order by coalesce(last_mission_update_at, last_progress_at, started_at, updated_at) desc,
                         updated_at desc
                """,
                (dup_drone_id,),
            ).fetchall()
            for stale in active[1:]:
                if transition_task(conn, stale["task_code"], "aborted", "duplicate running task reclaimed", now=now):
                    reclaimed += 1
        conn.commit()
    return reclaimed


def ensure_task_indexes() -> None:
    with db_conn() as conn:
        conn.execute(
            "create unique index if not exists idx_inspection_tasks_one_running_per_drone "
            "on inspection_tasks(drone_id) where status='running'"
        )
        conn.execute(
            "create index if not exists idx_inspection_tasks_available "
            "on inspection_tasks(drone_id, status, published_at, created_at)"
        )
        conn.commit()


def task_sweeper_loop() -> None:
    while not task_sweeper_stop.wait(max(1.0, TASK_SWEEP_INTERVAL_SECONDS)):
        try:
            reconcile_task_states()
        except Exception:
            logger.exception("task timeout sweep failed")


def serialize_task(row: sqlite3.Row, shelves: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = row_to_dict(row)
    data["shelf_ids"] = [item["shelf_code"] for item in shelves]
    data["shelves"] = shelves
    return data


def get_task_payload(task_code: str) -> Optional[Dict[str, Any]]:
    reconcile_task_states()
    with db_conn() as conn:
        row = conn.execute("select * from inspection_tasks where task_code=?", (task_code,)).fetchone()
        if not row:
            return None
        shelves = conn.execute(
            "select shelf_code, sort_order from inspection_task_shelves where task_code=? order by sort_order",
            (task_code,),
        ).fetchall()
        return serialize_task(row, [row_to_dict(s) for s in shelves])


def get_active_task_code(drone_id: int) -> str:
    with db_conn() as conn:
        row = conn.execute(
            """
            select task_code from inspection_tasks
            where drone_id=? and status='running'
            order by coalesce(last_mission_update_at, last_progress_at, started_at, updated_at) desc limit 1
            """,
            (drone_id,),
        ).fetchone()
        return str(row["task_code"]) if row else ""


def upsert_task(task_code: str, drone_id: int, name: str, shelf_ids: List[str], status: str = "published") -> Dict[str, Any]:
    if not task_code:
        raise ValueError("task_code is required")
    normalized = [str(item).strip() for item in shelf_ids if str(item).strip()]
    if not normalized:
        raise ValueError("shelf_ids is required")
    if len(normalized) != len(set(normalized)):
        raise ValueError("shelf_ids contains duplicates")
    now = time.time()
    with db_conn() as conn:
        existing = conn.execute(
            "select status from inspection_tasks where task_code=?", (task_code,)
        ).fetchone()
        if existing and existing["status"] == "running":
            raise ValueError("running task cannot be republished")
        conn.execute(
            """
            insert into inspection_tasks(task_code, drone_id, name, status, created_at, updated_at, published_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(task_code) do update set
                drone_id=excluded.drone_id,
                name=excluded.name,
                status=excluded.status,
                execution_phase='',
                updated_at=excluded.updated_at,
                published_at=excluded.published_at,
                started_at=null,
                completed_at=null,
                failed_at=null,
                aborted_at=null,
                last_mission_update_at=null,
                last_progress_at=null,
                status_reason='republished'
            """,
            (task_code, drone_id, name or task_code, status, now, now, now if status == "published" else None),
        )
        conn.execute("delete from inspection_task_shelves where task_code=?", (task_code,))
        for idx, shelf_code in enumerate(normalized, 1):
            conn.execute(
                "insert into inspection_task_shelves(task_code, sort_order, shelf_code) values (?, ?, ?)",
                (task_code, idx, shelf_code),
            )
        conn.commit()
    task = get_task_payload(task_code)
    if not task:
        raise RuntimeError("task save failed")
    return task

@app.get("/api/drones/{drone_id}/tasks/available")
def tasks_available(drone_id: int) -> Dict[str, Any]:
    reconcile_task_states(drone_id)
    with db_conn() as conn:
        row = conn.execute(
            """
            select * from inspection_tasks
            where drone_id=? and status='running'
            order by coalesce(last_mission_update_at, last_progress_at, started_at, updated_at) desc limit 1
            """,
            (drone_id,),
        ).fetchone()
        if not row:
            pending_stop = conn.execute(
                "select id from drone_commands where drone_id=? and command='STOP_MISSION' and status='pending' limit 1",
                (drone_id,),
            ).fetchone()
            if pending_stop:
                return {"success": True, "data": {}}
            row = conn.execute(
                """
                select * from inspection_tasks
                where drone_id=? and status in ('pending', 'published')
                order by coalesce(published_at, created_at) asc, created_at asc limit 1
                """,
                (drone_id,),
            ).fetchone()
        if not row:
            return {"success": True, "data": {}}
        shelves = conn.execute(
            "select shelf_code, sort_order from inspection_task_shelves where task_code=? order by sort_order",
            (row["task_code"],),
        ).fetchall()
        return {"success": True, "data": serialize_task(row, [row_to_dict(s) for s in shelves])}







@app.post("/api/drones/{drone_id}/rfid/upload")
async def rfid_upload(drone_id: int, request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"detail": "invalid RFID upload payload"}, status_code=400)

    update_drone_from_payload(drone_id, payload)
    task_code = normalize_task_code(payload.get("task_code")) or get_active_task_code(drone_id)
    return_origin = payload.get("return_origin") if isinstance(payload.get("return_origin"), dict) else {}
    raw_items = payload.get("payload") if isinstance(payload.get("payload"), list) else []

    # Keep one mission record per EPC. The strongest RSSI sample is retained while
    # read_count reflects repeated reads, which makes the upload idempotent enough
    # for bridge retry after a transient network failure.
    unique: Dict[str, Dict[str, Any]] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        epc = str(raw.get("epc") or raw.get("rfid") or "").strip().upper()
        if not epc:
            continue
        item = {
            "epc": epc,
            "rssi": raw.get("rssi_dbm", raw.get("rssi")),
            "pc": raw.get("pc"),
            "read_count": int(raw.get("read_count") or 1),
            "first_seen_at": raw.get("first_seen_at") or raw.get("stamp") or payload.get("timestamp") or time.time(),
            "last_seen_at": raw.get("last_seen_at") or raw.get("stamp") or payload.get("timestamp") or time.time(),
        }
        previous = unique.get(epc)
        if previous is None:
            unique[epc] = item
            continue
        previous["read_count"] += item["read_count"]
        previous["last_seen_at"] = max(previous["last_seen_at"], item["last_seen_at"])
        try:
            if float(item["rssi"]) > float(previous["rssi"]):
                previous["rssi"] = item["rssi"]
                previous["pc"] = item["pc"]
        except (TypeError, ValueError):
            pass

    saved = save_rfid_scan_records("drone_mission", list(unique.values()), task_code)
    append_task_rfid_files(task_code, drone_id, return_origin, saved["records"])
    return {
        "success": True,
        "message": "RFID mission upload saved",
        "data": {
            "drone_id": drone_id,
            "task_code": task_code or None,
            "return_origin": return_origin,
            "unique_epc_count": len(saved["records"]),
            "session_id": saved["session_id"],
        },
    }


@app.post("/api/drones/{drone_id}/waypoints/{waypoint_id}/commands/enter")
async def waypoint_enter(drone_id: int, waypoint_id: str, request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    context = {}
    task_code = ""
    if isinstance(payload, dict):
        update_drone_from_payload(drone_id, payload)
        task_code = normalize_task_code(payload.get("task_code")) or get_active_task_code(drone_id)
        context = resolve_waypoint_context(
            drone_id, task_code, waypoint_id, payload, status="inspecting"
        )
        mark_task_progress(task_code, f"waypoint {waypoint_id} entered")
    qr = frame_store.set_qr_detection(True, mode="task", reset=True) if task_code else frame_store.qr_control_status()
    return {
        "success": True,
        "message": "waypoint inspection started",
        "data": {"drone_id": drone_id, "waypoint_id": waypoint_id, "context": context, "qr": qr},
    }


@app.post("/api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive")
async def waypoint_arrive(drone_id: int, waypoint_id: str, request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    context = {}
    if isinstance(payload, dict):
        update_drone_from_payload(drone_id, payload)
        task_code = normalize_task_code(payload.get("task_code")) or get_active_task_code(drone_id)
        context = resolve_waypoint_context(drone_id, task_code, waypoint_id, payload, status="arrived")
        mark_task_progress(task_code, f"waypoint {waypoint_id} arrived")
    qr = frame_store.qr_control_status()
    if qr.get("mode") == "task":
        qr = frame_store.set_qr_detection(False)
    return {
        "success": True,
        "message": "waypoint arrival received",
        "data": {"drone_id": drone_id, "waypoint_id": waypoint_id, "context": context, "qr": qr},
    }


def expire_stale_start_requests(max_age: float = MISSION_START_TIMEOUT_SECONDS) -> None:
    # Compatibility wrapper for older call sites. Reconciliation now handles both
    # starting and running tasks using their independent configured timeouts.
    reconcile_task_states()


@app.get("/api/tasks")
def list_tasks() -> List[Dict[str, Any]]:
    expire_stale_start_requests()
    with db_conn() as conn:
        rows = conn.execute("select * from inspection_tasks order by updated_at desc").fetchall()
        result = []
        for row in rows:
            shelves = conn.execute(
                "select shelf_code, sort_order from inspection_task_shelves where task_code=? order by sort_order",
                (row["task_code"],),
            ).fetchall()
            result.append(serialize_task(row, [row_to_dict(s) for s in shelves]))
        return result


@app.post("/api/tasks")
async def publish_task(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
        task_code = normalize_task_code(payload.get("task_code"))
        drone_id = int(payload.get("drone_id") or VIDEO_DRONE_ID)
        shelf_ids = payload.get("shelf_ids") or payload.get("shelves") or []
        task = upsert_task(task_code, drone_id, payload.get("name") or task_code, shelf_ids, "published")
        return {"success": True, "message": "task published", "data": task}
    except Exception as exc:
        return JSONResponse({"success": False, "detail": str(exc)}, status_code=400)


@app.post("/api/tasks/{task_code}/start")
def start_task(task_code: str) -> Dict[str, Any]:
    now = time.time()
    task = get_task_payload(task_code)
    if not task:
        return JSONResponse({"detail": "task not found"}, status_code=404)
    drone_id = int(task.get("drone_id") or VIDEO_DRONE_ID)
    with db_conn() as conn:
        conn.execute("begin immediate")
        current = conn.execute("select status from inspection_tasks where task_code=?", (task_code,)).fetchone()
        if not current or current["status"] not in {"pending", "published"}:
            conn.rollback()
            return JSONResponse({"detail": f"task is not startable: {current['status'] if current else 'missing'}"}, status_code=409)
        active = conn.execute(
            "select task_code from inspection_tasks where drone_id=? and status='running' limit 1",
            (drone_id,),
        ).fetchone()
        if active:
            conn.rollback()
            return JSONResponse({"detail": f"drone already has running task {active['task_code']}"}, status_code=409)
        queued = conn.execute(
            "select task_code from drone_commands where drone_id=? and command='START_MISSION' and status='pending' limit 1",
            (drone_id,),
        ).fetchone()
        if queued:
            conn.rollback()
            if queued["task_code"] == task_code:
                return {"success": True, "message": "start command already queued", "data": task}
            return JSONResponse({"detail": f"drone already has queued task {queued['task_code']}"}, status_code=409)
        transition_task(conn, task_code, "published", "start command queued", new_phase="dispatching", now=now)
        conn.execute("update inspection_tasks set started_at=coalesce(started_at, ?) where task_code=?", (now, task_code))
        conn.execute(
            "insert into drone_commands(drone_id, task_code, command, payload_json, status, created_at) values (?, ?, ?, ?, 'pending', ?)",
            (drone_id, task_code, "START_MISSION", json.dumps(task, ensure_ascii=False), now),
        )
        conn.commit()
    # Formal QR inspection starts only after the drone enters a task waypoint.
    if frame_store.qr_control_status().get("mode") == "manual":
        frame_store.set_qr_detection(False)
    return {"success": True, "message": "start command queued", "data": get_task_payload(task_code)}


@app.delete("/api/tasks/{task_code}")
def delete_task(task_code: str) -> Dict[str, Any]:
    """Delete a task and its shelf plan. Not a flight command."""
    with db_conn() as conn:
        row = conn.execute(
            "select task_code, status from inspection_tasks where task_code=?",
            (task_code,),
        ).fetchone()
        if not row:
            return JSONResponse({"detail": "task not found"}, status_code=404)
        if row["status"] == "running":
            return JSONResponse({"detail": "task is running; stop it first"}, status_code=409)
        conn.execute("begin immediate")
        conn.execute("delete from inspection_task_shelves where task_code=?", (task_code,))
        cur = conn.execute("delete from inspection_tasks where task_code=?", (task_code,))
        conn.commit()
    return {"success": True, "message": "task deleted", "task_code": task_code, "deleted": cur.rowcount}


@app.post("/api/tasks/{task_code}/stop")
def stop_task(task_code: str) -> Dict[str, Any]:
    now = time.time()
    task = get_task_payload(task_code)
    if not task:
        return JSONResponse({"detail": "task not found"}, status_code=404)
    drone_id = int(task.get("drone_id") or VIDEO_DRONE_ID)
    with db_conn() as conn:
        current = conn.execute("select status from inspection_tasks where task_code=?", (task_code,)).fetchone()
        if not current or current["status"] != "running":
            return JSONResponse({"detail": "task is not running"}, status_code=409)
        transition_task(conn, task_code, "running", "stop command queued", new_phase="stopping", now=now)
        conn.execute(
            "insert into drone_commands(drone_id, task_code, command, payload_json, status, created_at) values (?, ?, ?, ?, 'pending', ?)",
            (drone_id, task_code, "STOP_MISSION", json.dumps(task, ensure_ascii=False), now),
        )
        conn.commit()
    return {"success": True, "message": "stop command queued", "data": get_task_payload(task_code)}


@app.post("/api/drones/{drone_id}/tasks/current/abort")
def abort_current_task(drone_id: int) -> Dict[str, Any]:
    now = time.time()
    with db_conn() as conn:
        conn.execute("begin immediate")
        row = conn.execute(
            "select * from inspection_tasks where drone_id=? and status='running' order by updated_at desc limit 1",
            (drone_id,),
        ).fetchone()
        if not row:
            row = conn.execute(
                """
                select * from inspection_tasks
                where drone_id=? and status='aborted' and status_reason like 'manually aborted%'
                  and updated_at>=?
                order by updated_at desc limit 1
                """,
                (drone_id, now - 600),
            ).fetchone()
            if not row:
                conn.rollback()
                return JSONResponse({"detail": "drone has no running task"}, status_code=404)
        task_code = str(row["task_code"])
        conn.execute(
            "update drone_commands set status='cancelled', consumed_at=? where drone_id=? and task_code=? and command='START_MISSION' and status='pending'",
            (now, drone_id, task_code),
        )
        pending_stop = conn.execute(
            "select id from drone_commands where drone_id=? and task_code=? and command='STOP_MISSION' and status='pending' limit 1",
            (drone_id, task_code),
        ).fetchone()
        if not pending_stop:
            shelves = conn.execute(
                "select shelf_code, sort_order from inspection_task_shelves where task_code=? order by sort_order",
                (task_code,),
            ).fetchall()
            task_payload = serialize_task(row, [row_to_dict(item) for item in shelves])
            conn.execute(
                "insert into drone_commands(drone_id, task_code, command, payload_json, status, created_at) values (?, ?, 'STOP_MISSION', ?, 'pending', ?)",
                (drone_id, task_code, json.dumps(task_payload, ensure_ascii=False), now),
            )
        transition_task(conn, task_code, "aborted", "manually aborted by ground station; stop command queued", now=now)
        conn.commit()
    if frame_store.qr_control_status().get("mode") == "task":
        frame_store.set_qr_detection(False)
    return {"success": True, "message": "current task aborted and stop command queued", "data": {"drone_id": drone_id, "task_code": task_code, "stop_command_queued": True}}


@app.get("/api/drones/{drone_id}/commands/poll")
def poll_drone_command(drone_id: int) -> Dict[str, Any]:
    reconcile_task_states(drone_id)
    now = time.time()
    with db_conn() as conn:
        conn.execute("begin immediate")
        row = conn.execute(
            "select * from drone_commands where drone_id=? and status='pending' order by id asc limit 1",
            (drone_id,),
        ).fetchone()
        if not row:
            return {"success": True, "data": {}}
        if row["command"] == "START_MISSION" and row["task_code"]:
            task_row = conn.execute(
                "select status from inspection_tasks where task_code=? and drone_id=?", (row["task_code"], drone_id)
            ).fetchone()
            active = conn.execute(
                "select task_code from inspection_tasks where drone_id=? and status='running' limit 1", (drone_id,)
            ).fetchone()
            if not task_row or task_row["status"] not in {"pending", "published"} or active:
                conn.execute("update drone_commands set status='cancelled', consumed_at=? where id=?", (now, row["id"]))
                conn.commit()
                logger.warning(
                    "start command cancelled drone_id=%s task_code=%s active_task=%s timestamp=%.3f",
                    drone_id, row["task_code"], active["task_code"] if active else "", now,
                )
                return {"success": True, "data": {}}
            conn.execute(
                """
                insert into drone_task_context(drone_id, task_code, shelf_code, waypoint_id, waypoint_index, status, updated_at)
                values (?, ?, '', '', null, 'starting', ?)
                on conflict(drone_id) do update set task_code=excluded.task_code, shelf_code='', waypoint_id='', waypoint_index=null, status='starting', updated_at=excluded.updated_at
                """,
                (drone_id, row["task_code"], now),
            )
            conn.execute(
                "update inspection_tasks set started_at=coalesce(started_at, ?), last_progress_at=? where task_code=?",
                (now, now, row["task_code"]),
            )
            transition_task(conn, row["task_code"], "running", "start command consumed", new_phase="starting", now=now)
        if row["command"] == "STOP_MISSION" and row["task_code"]:
            transition_task(conn, row["task_code"], "running", "stop command consumed", new_phase="stopping", now=now)
        conn.execute("update drone_commands set status='consumed', consumed_at=? where id=?", (now, row["id"]))
        conn.commit()
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        return {"success": True, "data": {"id": row["id"], "command": row["command"], "task_code": row["task_code"], "payload": payload}}


@app.post("/api/drones/{drone_id}/mission/status")
async def mission_status(drone_id: int, request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    status = str(payload.get("status") or "").strip().lower()
    task_code = normalize_task_code(payload.get("task_code")) or get_active_task_code(drone_id)
    allowed = {"starting", "running", "completed", "stopped", "error"}
    if status not in allowed:
        return JSONResponse({"detail": "invalid status"}, status_code=400)
    now = time.time()
    message = str(payload.get("message") or "").strip()
    status_map = {
        "starting": ("running", "starting"),
        "running": ("running", "running"),
        "completed": ("completed", ""),
        "stopped": ("aborted", ""),
        "error": ("failed", ""),
    }
    canonical_status, phase = status_map[status]
    if not task_code:
        return JSONResponse({"detail": "no active task found"}, status_code=404)
    with db_conn() as conn:
        task_row = conn.execute(
            "select status from inspection_tasks where task_code=? and drone_id=?", (task_code, drone_id)
        ).fetchone()
        if not task_row:
            return JSONResponse({"detail": "task not found for drone"}, status_code=404)
        if task_row["status"] in TERMINAL_TASK_STATUSES:
            return {"success": True, "message": "terminal task status ignored", "data": {"drone_id": drone_id, "task_code": task_code, "status": task_row["status"], "ignored": True}}
        conn.execute(
            """
            insert into drone_task_context(drone_id, task_code, shelf_code, waypoint_id, waypoint_index, status, updated_at)
            values (?, ?, '', '', null, ?, ?)
            on conflict(drone_id) do update set task_code=excluded.task_code, status=excluded.status, updated_at=excluded.updated_at
            """,
            (drone_id, task_code, phase or canonical_status, now),
        )
        if status in {"starting", "running"}:
            conn.execute(
                "update inspection_tasks set last_mission_update_at=?, last_progress_at=? where task_code=?",
                (now, now, task_code),
            )
        reason = message or f"mission reported {status}"
        transition_task(conn, task_code, canonical_status, reason, new_phase=phase, now=now)
        if canonical_status in TERMINAL_TASK_STATUSES:
            conn.execute(
                "update drone_commands set status='cancelled', consumed_at=? where drone_id=? and task_code=? and status='pending'",
                (now, drone_id, task_code),
            )
        conn.commit()
    if status in {"completed", "stopped", "error"} and frame_store.qr_control_status().get("mode") == "task":
        frame_store.set_qr_detection(False)
    if isinstance(payload, dict):
        update_drone_from_payload(drone_id, {
            "drone_code": payload.get("drone_code"),
            "status": drone_status_from_mission_status(status),
            "timestamp": payload.get("timestamp") or now,
        })
    return {"success": True, "message": "mission status received", "data": {"drone_id": drone_id, "task_code": task_code, "reported_status": status, "status": canonical_status, "execution_phase": phase}}


@app.get("/api/tasks/{task_code}/qr-records")
def list_task_qr_records(task_code: str, limit: int = 200) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            select * from qr_records
            where task_code=? and valid=1
            order by coalesce(first_seen_at, frame_time, created_at) asc, id asc
            limit ?
            """,
            (task_code, limit),
        ).fetchall()
        return [row_to_dict(r) for r in rows]

DB_VIEW_TABLES = {
    "drones",
    "shelves",
    "inspection_tasks",
    "inspection_task_shelves",
    "inventory_bindings",
    "rfid_scan_sessions",
    "rfid_scan_records",
    "drone_commands",
    "drone_task_context",
    "qr_records",
}

DB_DELETE_TABLES = {
    "shelves",
    "inspection_tasks",
    "inspection_task_shelves",
    "inventory_bindings",
    "rfid_scan_sessions",
    "rfid_scan_records",
    "drone_commands",
    "qr_records",
}


def db_table_meta(conn: sqlite3.Connection, table_name: str) -> Optional[Dict[str, Any]]:
    if table_name not in DB_VIEW_TABLES:
        return None
    exists = conn.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (table_name,),
    ).fetchone()
    if not exists:
        return None
    columns = [row_to_dict(r) for r in conn.execute(f"pragma table_info({table_name})").fetchall()]
    count = conn.execute(f"select count(*) from {table_name}").fetchone()[0]
    return {"name": table_name, "count": count, "columns": columns, "can_delete": table_name in DB_DELETE_TABLES}



def db_rows_for_view(table_name: str, rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    if table_name == "drones":
        return [serialize_drone(r) for r in rows]
    return [row_to_dict(r) for r in rows]


def db_columns_for_view(table_name: str, columns: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if table_name != "drones" or not rows:
        return columns
    hidden = {"status", "raw_status"}
    existing = {c["name"] for c in columns}
    result = [c for c in columns if c["name"] not in hidden]
    for name in ["effective_status", "heartbeat_age", "online", "offline_after"]:
        if name not in existing:
            result.append({"cid": len(result), "name": name, "type": "VIEW", "notnull": 0, "dflt_value": None, "pk": 0})
    return result

def db_order_column(columns: List[Dict[str, Any]]) -> tuple[str, str]:
    names = [c["name"] for c in columns]
    order_col = "id" if "id" in names else ("updated_at" if "updated_at" in names else ("created_at" if "created_at" in names else names[0]))
    direction = "desc" if order_col in {"id", "updated_at", "created_at"} else "asc"
    return order_col, direction


@app.get("/api/db/tables")
def db_tables() -> List[Dict[str, Any]]:
    result = []
    with db_conn() as conn:
        for name in sorted(DB_VIEW_TABLES):
            meta = db_table_meta(conn, name)
            if meta:
                result.append(meta)
    return result


@app.get("/api/db/tables/{table_name}")
def db_table_rows(table_name: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    with db_conn() as conn:
        meta = db_table_meta(conn, table_name)
        if not meta:
            return JSONResponse({"detail": "table not found or not allowed"}, status_code=404)
        order_col, direction = db_order_column(meta["columns"])
        rows = conn.execute(f"select * from {table_name} order by {order_col} {direction} limit ? offset ?", (limit, offset)).fetchall()
        view_rows = db_rows_for_view(table_name, rows)
        view_columns = db_columns_for_view(table_name, meta["columns"], view_rows)
        return {"table": table_name, "count": meta["count"], "limit": limit, "offset": offset, "columns": view_columns, "rows": view_rows, "can_delete": meta["can_delete"]}


@app.get("/api/db/tables/{table_name}/export")
def export_db_table(table_name: str) -> Response:
    with db_conn() as conn:
        meta = db_table_meta(conn, table_name)
        if not meta:
            return JSONResponse({"detail": "table not found or not allowed"}, status_code=404)
        order_col, direction = db_order_column(meta["columns"])
        rows = conn.execute(f"select * from {table_name} order by {order_col} {direction}").fetchall()
    view_rows = db_rows_for_view(table_name, rows)
    view_columns = db_columns_for_view(table_name, meta["columns"], view_rows)
    column_names = [c["name"] for c in view_columns]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=column_names, extrasaction="ignore")
    writer.writeheader()
    for row in view_rows:
        writer.writerow(row)
    filename = f"{table_name}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.delete("/api/db/tables/{table_name}")
async def delete_db_table_rows(table_name: str, request: Request) -> Dict[str, Any]:
    if table_name not in DB_DELETE_TABLES:
        return JSONResponse({"detail": "table delete not allowed"}, status_code=403)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    ids = payload.get("ids") if isinstance(payload, dict) else None
    confirm = (payload.get("confirm") if isinstance(payload, dict) else "") or ""
    with db_conn() as conn:
        meta = db_table_meta(conn, table_name)
        if not meta:
            return JSONResponse({"detail": "table not found"}, status_code=404)
        names = [c["name"] for c in meta["columns"]]
        before = meta["count"]
        if ids:
            if "id" not in names:
                return JSONResponse({"detail": "row delete requires id column"}, status_code=400)
            clean_ids = [int(x) for x in ids if str(x).isdigit()]
            if not clean_ids:
                return JSONResponse({"detail": "no valid ids"}, status_code=400)
            placeholders = ",".join("?" for _ in clean_ids)
            conn.execute(f"delete from {table_name} where id in ({placeholders})", clean_ids)
        else:
            if confirm != table_name:
                return JSONResponse({"detail": "confirm must equal table name"}, status_code=400)
            conn.execute(f"delete from {table_name}")
        conn.commit()
        after = conn.execute(f"select count(*) from {table_name}").fetchone()[0]
    return {"success": True, "table": table_name, "deleted": before - after, "count": after}




def lookup_inventory_binding(epc: str, current_shelf: str = "") -> Dict[str, Any]:
    epc = (epc or "").strip().upper()
    current_shelf = (current_shelf or "").strip()
    with db_conn() as conn:
        row = conn.execute(
            "select * from inventory_bindings where upper(rfid)=? order by id limit 1",
            (epc,),
        ).fetchone()
        if not row:
            return {"match_status": "unbound", "result": "未绑定", "note": "RFID 未在基础绑定表中找到"}
        binding = row_to_dict(row)
        same_shelf = bool(current_shelf and current_shelf == binding.get("shelf_code"))
        if current_shelf:
            result = "位置正确" if same_shelf else "放错"
            note = "RFID 已绑定，且当前货架与绑定货架一致" if same_shelf else "RFID 已绑定，但当前货架与绑定货架不一致"
        else:
            result = "已绑定"
            note = "RFID 已绑定，未指定当前货架"
        return {"match_status": "matched" if same_shelf or not current_shelf else "wrong_shelf", "result": result, "note": note, "binding": binding}


def save_rfid_scan_records(mode: str, records: List[Dict[str, Any]], task_code: str = "", shelf_code: str = "") -> Dict[str, Any]:
    now = time.time()
    with db_conn() as conn:
        cur = conn.execute(
            "insert into rfid_scan_sessions(mode, task_code, status, started_at, stopped_at) values (?, ?, 'completed', ?, ?)",
            (mode, task_code or None, now, now),
        )
        session_id = cur.lastrowid
        saved = []
        for item in records:
            epc = (item.get("epc") or item.get("rfid") or "").strip().upper()
            if not epc:
                continue
            match = lookup_inventory_binding(epc, shelf_code)
            first_seen = item.get("first_seen_at") or item.get("seen_at") or now
            last_seen = item.get("last_seen_at") or item.get("seen_at") or now
            conn.execute(
                """
                insert into rfid_scan_records(session_id, task_code, rfid, epc, rssi, pc, read_count, first_seen_at, last_seen_at, shelf_code, match_status, note)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_code or None,
                    epc,
                    epc,
                    item.get("rssi"),
                    item.get("pc"),
                    int(item.get("read_count") or 1),
                    first_seen,
                    last_seen,
                    shelf_code or None,
                    match.get("match_status"),
                    match.get("note"),
                ),
            )
            saved.append({**item, **match, "session_id": session_id})
        conn.commit()
    return {"session_id": session_id, "records": saved}


def append_task_rfid_files(task_code: str, drone_id: int, return_origin: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    if not task_code:
        return
    task_dir = TASK_DATA_DIR / task_code
    task_dir.mkdir(parents=True, exist_ok=True)
    jsonl = task_dir / "rfid_records.jsonl"
    csv_path = task_dir / "rfid_records.csv"
    fields = [
        "task_code", "drone_id", "epc", "rssi", "pc", "read_count",
        "first_seen_at", "last_seen_at", "match_status", "result",
        "bound_sku", "bound_shelf", "return_origin_x", "return_origin_y", "return_origin_z",
    ]
    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        if write_header:
            writer.writeheader()
        for item in records:
            binding = item.get("binding") if isinstance(item.get("binding"), dict) else {}
            row = {
                "task_code": task_code,
                "drone_id": drone_id,
                "epc": item.get("epc") or item.get("rfid"),
                "rssi": item.get("rssi"),
                "pc": item.get("pc"),
                "read_count": item.get("read_count") or 1,
                "first_seen_at": item.get("first_seen_at") or item.get("seen_at"),
                "last_seen_at": item.get("last_seen_at") or item.get("seen_at"),
                "match_status": item.get("match_status"),
                "result": item.get("result"),
                "bound_sku": binding.get("sku"),
                "bound_shelf": binding.get("shelf_code"),
                "return_origin_x": return_origin.get("x"),
                "return_origin_y": return_origin.get("y"),
                "return_origin_z": return_origin.get("z"),
            }
            writer.writerow(row)
            with jsonl.open("a", encoding="utf-8") as json_file:
                json_file.write(json.dumps({**row, "return_origin": return_origin}, ensure_ascii=False) + "\n")


@app.get("/api/tasks/{task_code}/rfid-records")
def list_task_rfid_records(task_code: str, limit: int = 500) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 2000))
    with db_conn() as conn:
        rows = conn.execute(
            """
            select r.*, b.sku as bound_sku, b.shelf_code as bound_shelf
            from rfid_scan_records r
            left join inventory_bindings b on upper(b.rfid)=upper(coalesce(r.epc, r.rfid))
            where r.task_code=?
            order by r.id desc limit ?
            """,
            (task_code, limit),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.get("/api/rfid/status")
def rfid_status() -> Dict[str, Any]:
    return {"success": True, "data": rfid_service.status()}


@app.get("/api/rfid/ports")
def rfid_ports() -> Dict[str, Any]:
    return {"success": True, "data": {"ports": rfid_service.ports(), "default": rfid_service.port}}


@app.post("/api/rfid/connect")
async def rfid_connect(request: Request) -> Dict[str, Any]:
    payload = await request.json() if request.headers.get("content-length") else {}
    try:
        data = rfid_service.connect(
            port=(payload or {}).get("port"),
            baudrate=(payload or {}).get("baudrate"),
            power_dbm=(payload or {}).get("power_dbm") or RFID_SAFE_POWER_DBM,
        )
        return {"success": True, "data": data}
    except Exception as exc:
        logger.exception("rfid connect failed")
        return JSONResponse({"detail": str(exc), "data": rfid_service.status()}, status_code=400)


@app.post("/api/rfid/disconnect")
def rfid_disconnect() -> Dict[str, Any]:
    return {"success": True, "data": rfid_service.disconnect()}


@app.post("/api/rfid/stop")
def rfid_stop() -> Dict[str, Any]:
    with rfid_service.lock:
        rfid_service.stop_locked()
    return {"success": True, "data": rfid_service.status()}


@app.post("/api/rfid/scan-once")
async def rfid_scan_once(request: Request) -> Dict[str, Any]:
    payload = await request.json() if request.headers.get("content-length") else {}
    task_code = str((payload or {}).get("task_code") or "").strip()
    shelf_code = str((payload or {}).get("shelf_code") or "").strip()
    try:
        item = rfid_service.scan_once()
        saved = save_rfid_scan_records("single", [item], task_code, shelf_code)
        return {"success": True, "data": saved}
    except Exception as exc:
        message = str(exc)
        if "no tag" in message.lower() or "0x15" in message.lower():
            return {
                "success": True,
                "data": {
                    "session_id": None,
                    "records": [],
                    "no_tag": True,
                    "message": "本次未读到 RFID 标签，请调整距离、角度或改用限时扫描。",
                    "status": rfid_service.status(),
                },
            }
        logger.warning("rfid scan once failed: %s", exc)
        return JSONResponse({"detail": message, "data": rfid_service.status()}, status_code=400)


@app.post("/api/rfid/scan-window")
async def rfid_scan_window(request: Request) -> Dict[str, Any]:
    payload = await request.json() if request.headers.get("content-length") else {}
    duration = min(float((payload or {}).get("duration") or 3), RFID_SCAN_MAX_SECONDS)
    task_code = str((payload or {}).get("task_code") or "").strip()
    shelf_code = str((payload or {}).get("shelf_code") or "").strip()
    try:
        records = rfid_service.scan_window(duration)
        saved = save_rfid_scan_records("window", records, task_code, shelf_code)
        return {"success": True, "data": saved}
    except Exception as exc:
        logger.warning("rfid scan window failed: %s", exc)
        return JSONResponse({"detail": str(exc), "data": rfid_service.status()}, status_code=400)


@app.get("/api/rfid/records")
def list_rfid_records(limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    with db_conn() as conn:
        rows = conn.execute("select * from rfid_scan_records order by id desc limit ?", (limit,)).fetchall()
        return [row_to_dict(r) for r in rows]

@app.get("/api/shelves")

def list_shelves() -> List[Dict[str, Any]]:

    with db_conn() as conn:

        rows = conn.execute("select * from shelves order by shelf_code").fetchall()

        return [row_to_dict(r) for r in rows]






@app.get("/api/inventory-bindings")
def list_inventory_bindings() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            select b.*, s.shelf_name
            from inventory_bindings b
            left join shelves s on s.shelf_code=b.shelf_code
            order by b.updated_at desc, b.id desc
            """
        ).fetchall()
        return [row_to_dict(r) for r in rows]


@app.post("/api/inventory-bindings")
async def save_inventory_binding(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    rfid = str(payload.get("rfid") or "").strip()
    sku = str(payload.get("sku") or payload.get("text") or "").strip()
    shelf_code = str(payload.get("shelf_code") or "").strip()
    if not rfid or not sku or not shelf_code:
        return JSONResponse({"detail": "rfid, sku and shelf_code are required"}, status_code=400)
    now = time.time()
    with db_conn() as conn:
        shelf = conn.execute("select 1 from shelves where shelf_code=?", (shelf_code,)).fetchone()
        if not shelf:
            return JSONResponse({"detail": "shelf not found"}, status_code=400)
        existing = conn.execute(
            "select id from inventory_bindings where rfid=? or sku=? order by id limit 1",
            (rfid, sku),
        ).fetchone()
        if existing:
            conn.execute("delete from inventory_bindings where (rfid=? or sku=?) and id<>?", (rfid, sku, existing["id"]))
            conn.execute(
                "update inventory_bindings set rfid=?, sku=?, shelf_code=?, updated_at=? where id=?",
                (rfid, sku, shelf_code, now, existing["id"]),
            )
            binding_id = existing["id"]
        else:
            cur = conn.execute(
                "insert into inventory_bindings(rfid, sku, shelf_code, created_at, updated_at) values (?, ?, ?, ?, ?)",
                (rfid, sku, shelf_code, now, now),
            )
            binding_id = cur.lastrowid
        conn.commit()
        row = conn.execute("select * from inventory_bindings where id=?", (binding_id,)).fetchone()
    return {"success": True, "data": row_to_dict(row)}


@app.delete("/api/inventory-bindings/{binding_id}")
def delete_inventory_binding(binding_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        cur = conn.execute("delete from inventory_bindings where id=?", (binding_id,))
        conn.commit()
    return {"success": True, "deleted": cur.rowcount}


@app.delete("/api/inventory-bindings")
async def clear_inventory_bindings(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or payload.get("confirm") != "inventory_bindings":
        return JSONResponse({"detail": "confirm must equal inventory_bindings"}, status_code=400)
    with db_conn() as conn:
        before = conn.execute("select count(*) from inventory_bindings").fetchone()[0]
        conn.execute("delete from inventory_bindings")
        conn.commit()
    return {"success": True, "deleted": before}


@app.get("/api/frame/{drone_id}/{mode}.jpg")
def latest_frame_jpg(drone_id: int, mode: str) -> Response:
    if mode not in {"raw", "processed"}:
        return JSONResponse({"detail": "invalid mode"}, status_code=400)
    latest = frame_store.get(drone_id, mode)
    if not latest:
        return JSONResponse({"detail": "frame not found"}, status_code=404)
    return Response(content=latest["frame"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/qr-records")
def list_qr_records(limit: int = 80) -> List[Dict[str, Any]]:
    # This endpoint serves the front-end QR test panel only.
    # It intentionally does not read from or write to qr_records.
    return frame_store.list_qr_items(limit)





@app.websocket("/ws/video/{drone_id}/{mode}")

async def ws_video(websocket: WebSocket, drone_id: int, mode: str) -> None:

    if mode not in {"raw", "processed"}:

        await websocket.close(code=4400)

        return

    await websocket.accept()

    key = (drone_id, mode)
    stale_clients: List[WebSocket] = []

    async with video_ws_lock:

        clients = video_ws_clients.setdefault(key, [])

        clients.append(websocket)

        while len(clients) > VIDEO_WS_MAX_PER_STREAM:

            stale_clients.append(clients.pop(0))

        logger.info("video websocket connected drone_id=%s mode=%s active=%s max=%s stale_to_close=%s", drone_id, mode, len(clients), VIDEO_WS_MAX_PER_STREAM, len(stale_clients))

    # Do not await closing old browser connections while holding video_ws_lock.
    # Some stale WebSockets never complete close promptly, which blocks the new
    # client before it reaches the frame-send loop. Close them best-effort with
    # a short timeout after the new client is registered.
    for old_ws in stale_clients:

        try:

            await asyncio.wait_for(old_ws.close(code=4409, reason="video stream connection replaced"), timeout=0.2)

        except Exception:

            pass

    last_seq = -1

    last_qr = ""

    try:

        while True:

            latest = frame_store.get(drone_id, mode)

            if latest and latest["seq"] != last_seq:

                last_seq = latest["seq"]

                if mode == "processed":

                    qr_payload = json.dumps(latest.get("items") or [], ensure_ascii=False, sort_keys=True)

                    if qr_payload != last_qr:

                        last_qr = qr_payload

                        await websocket.send_json({"type": "qr", "items": latest.get("items") or [], "updated_at": latest.get("updated_at")})

                await websocket.send_bytes(latest["frame"])

            elif not latest:

                await websocket.send_json({"type": "waiting", "message": "等待视频流"})

                await asyncio.sleep(1.0)

                continue

            await asyncio.sleep(VIDEO_WS_SEND_INTERVAL)

    except WebSocketDisconnect:

        return

    except Exception as exc:

        logger.info("video websocket closed drone_id=%s mode=%s: %s", drone_id, mode, exc)

    finally:

        async with video_ws_lock:

            clients = video_ws_clients.get(key) or []

            if websocket in clients:

                clients.remove(websocket)

            if not clients and key in video_ws_clients:

                video_ws_clients.pop(key, None)

            logger.info("video websocket disconnected drone_id=%s mode=%s active=%s", drone_id, mode, len(clients))
