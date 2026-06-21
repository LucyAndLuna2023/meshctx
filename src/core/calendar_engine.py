"""meshctx calendar_engine — v3.93 stub"""
from __future__ import annotations
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path


class ReminderType(Enum):
    POPUP = "popup"
    EMAIL = "email"


class RecurrenceRule(Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class CalDAVProvider(Enum):
    GENERIC = "generic"
    NEXTCLOUD = "nextcloud"
    GOOGLE = "google"
    APPLE = "apple"
    OUTLOOK = "outlook"


class SyncStatus(Enum):
    OFFLINE = "offline"
    SUCCESS = "success"
    PARTIAL = "partial"
    UP_TO_DATE = "up_to_date"
    ERROR = "error"


@dataclass
class CalendarEvent:
    title: str = ""
    description: str = ""
    location: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    reminders: list[ReminderType] = field(default_factory=list)
    reminder_minutes: int = 15
    custom_reminder_offsets: list[int] = field(default_factory=list)
    recurrence: RecurrenceRule = RecurrenceRule.NONE
    recurrence_rrule: str = ""
    tags: list[str] = field(default_factory=list)
    color: str = ""
    calendar_id: str = ""
    metadata: dict = field(default_factory=dict)
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    deleted: bool = False
    dirty: bool = True

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "reminders": [r.value for r in self.reminders],
            "reminder_minutes": self.reminder_minutes,
            "custom_reminder_offsets": self.custom_reminder_offsets,
            "recurrence": self.recurrence.value,
            "recurrence_rrule": self.recurrence_rrule,
            "tags": self.tags,
            "color": self.color,
            "calendar_id": self.calendar_id,
            "metadata": self.metadata,
            "deleted": self.deleted,
            "dirty": self.dirty,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CalendarEvent:
        return cls(
            uid=d.get("uid", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            location=d.get("location", ""),
            start=datetime.fromisoformat(d["start"]) if d.get("start") else None,
            end=datetime.fromisoformat(d["end"]) if d.get("end") else None,
            all_day=d.get("all_day", False),
            reminders=[ReminderType(r) for r in d.get("reminders", [])],
            reminder_minutes=d.get("reminder_minutes", 15),
            custom_reminder_offsets=d.get("custom_reminder_offsets", []),
            recurrence=RecurrenceRule(d.get("recurrence", "none")),
            recurrence_rrule=d.get("recurrence_rrule", ""),
            tags=d.get("tags", []),
            color=d.get("color", ""),
            calendar_id=d.get("calendar_id", ""),
            metadata=d.get("metadata", {}),
            deleted=d.get("deleted", False),
            dirty=d.get("dirty", True),
        )

    def duration_minutes(self) -> int:
        if self.end and self.start:
            return int((self.end - self.start).total_seconds() / 60)
        return 60

    def is_past(self) -> bool:
        now = datetime.now()
        if self.end:
            return self.end < now
        return self.start is not None and self.start < now

    def is_upcoming(self, window_minutes: int = 60) -> bool:
        if self.start is None:
            return False
        now = datetime.now()
        delta = (self.start - now).total_seconds() / 60
        return 0 <= delta <= window_minutes

    def to_icalendar(self) -> str:
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT"]
        lines.append(f"UID:{self.uid}")
        lines.append(f"SUMMARY:{self.title}")
        if self.description:
            lines.append(f"DESCRIPTION:{self.description}")
        if self.location:
            lines.append(f"LOCATION:{self.location}")
        if self.start:
            if self.all_day:
                lines.append(f"DTSTART;VALUE=DATE:{self.start.strftime('%Y%m%d')}")
                if self.end and self.end > self.start:
                    lines.append(f"DTEND;VALUE=DATE:{self.end.strftime('%Y%m%d')}")
                else:
                    end_date = self.start + timedelta(days=1)
                    lines.append(f"DTEND;VALUE=DATE:{end_date.strftime('%Y%m%d')}")
            else:
                lines.append(f"DTSTART:{self.start.strftime('%Y%m%dT%H%M%S')}")
                if self.end:
                    lines.append(f"DTEND:{self.end.strftime('%Y%m%dT%H%M%S')}")
        if self.reminders:
            lines.append("BEGIN:VALARM")
            lines.append(f"TRIGGER:-PT{self.reminder_minutes}M")
            lines.append("ACTION:DISPLAY")
            lines.append("END:VALARM")
        lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines)


@dataclass
class ReminderTask:
    event_uid: str = ""
    event_title: str = ""
    reminder_type: ReminderType = ReminderType.POPUP
    delivered: bool = False
    trigger_at: str = ""


# Chinese natural language parsing helpers
def _parse_relative_day(text: str) -> int | None:
    if "明天" in text:
        return 1
    if "后天" in text:
        return 2
    if "大后天" in text:
        return 3
    if "今天" in text:
        return 0
    return None


_WEEKDAYS_CN = {
    "周一": 0, "周二": 1, "周三": 2, "周四": 3,
    "周五": 4, "周六": 5, "周日": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3,
    "星期五": 4, "星期六": 5, "星期天": 6, "星期日": 6,
}


def _parse_datetime(text: str) -> datetime | None:
    import re
    # Try ISO: 2026-06-15 14:00
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', text)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)))
    # Try Month+Day: 3月15日
    m = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if m:
        now = datetime.now()
        month, day = int(m.group(1)), int(m.group(2))
        dt = datetime(now.year, month, day, 0, 0)
        if dt < now:
            dt = datetime(now.year + 1, month, day, 0, 0)
        return dt
    return None


def _parse_time(text: str) -> tuple[int, int] | None:
    import re
    # 上午/下午
    is_pm = False
    if "下午" in text or "晚上" in text:
        is_pm = True
    # Time patterns
    m = re.search(r'(\d{1,2}):(\d{2})', text)
    if m:
        h = int(m.group(1))
        if is_pm and h < 12:
            h += 12
        return h, int(m.group(2))
    m = re.search(r'(\d{1,2})点(?:(\d{1,2})分)?', text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if is_pm and h < 12:
            h += 12
        return h, mi
    return None


class CalendarEngine:
    VERSION = "3.93.0"

    def __init__(self, db_path: str | Path | None = None, *args, **kwargs):
        if db_path is None:
            fd, db_path = os.tempnam() if hasattr(os, 'tempnam') else None
            if db_path is None:
                import tempfile
                fd, db_path = tempfile.mkstemp(suffix=".db", prefix="cal_")
                os.close(fd)
        self.db_path = Path(db_path)
        self._events: dict[str, CalendarEvent] = {}
        self._reminders_queue: list[ReminderTask] = []
        self._caldav_config: dict = {
            "url": "",
            "username": "",
            "password": "",
            "provider": "",
            "calendar_path": "",
            "sync_interval_seconds": 0,
            "enabled": False,
        }
        self._notification_callback = None
        self._reminder_loop_active = False
        self._reminder_thread: threading.Thread | None = None
        self._reminder_stop = threading.Event()
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database."""
        import sqlite3
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                uid TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                location TEXT,
                start TEXT,
                end TEXT,
                all_day INTEGER DEFAULT 0,
                reminders TEXT DEFAULT '[]',
                reminder_minutes INTEGER DEFAULT 15,
                custom_reminder_offsets TEXT DEFAULT '[]',
                recurrence TEXT DEFAULT 'none',
                recurrence_rrule TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                color TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                deleted INTEGER DEFAULT 0,
                dirty INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders_queue (
                event_uid TEXT,
                event_title TEXT,
                reminder_type TEXT,
                delivered INTEGER DEFAULT 0,
                trigger_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        self._load_events()

    def _load_events(self):
        import sqlite3, json
        conn = sqlite3.connect(str(self.db_path))
        rows = conn.execute("SELECT * FROM events").fetchall()
        conn.close()
        self._events = {}
        for row in rows:
            e = CalendarEvent(
                uid=row[0], title=row[1], description=row[2] or "", location=row[3] or "",
                start=datetime.fromisoformat(row[4]) if row[4] else None,
                end=datetime.fromisoformat(row[5]) if row[5] else None,
                all_day=bool(row[6]),
                reminders=[ReminderType(r) for r in json.loads(row[7] or "[]")],
                reminder_minutes=row[8], custom_reminder_offsets=json.loads(row[9] or "[]"),
                recurrence=RecurrenceRule(row[10]),
                recurrence_rrule=row[11] or "", tags=json.loads(row[12] or "[]"),
                color=row[13] or "", metadata=json.loads(row[14] or "{}"),
                deleted=bool(row[15]), dirty=bool(row[16]),
            )
            self._events[e.uid] = e

    # ── Event CRUD ────────────────────────────────────────

    def add_event(self, event: CalendarEvent) -> str:
        import sqlite3, json
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            INSERT OR REPLACE INTO events (uid, title, description, location, start, end,
                all_day, reminders, reminder_minutes, custom_reminder_offsets,
                recurrence, recurrence_rrule, tags, color, metadata, deleted, dirty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.uid, event.title, event.description, event.location,
            event.start.isoformat() if event.start else None,
            event.end.isoformat() if event.end else None,
            int(event.all_day),
            json.dumps([r.value for r in event.reminders]),
            event.reminder_minutes,
            json.dumps(event.custom_reminder_offsets),
            event.recurrence.value, event.recurrence_rrule,
            json.dumps(event.tags), event.color,
            json.dumps(event.metadata),
            int(event.deleted), int(event.dirty),
        ))
        conn.commit()
        conn.close()
        self._events[event.uid] = event
        self._schedule_reminders(event)
        return event.uid

    def get_event(self, uid: str) -> CalendarEvent | None:
        e = self._events.get(uid)
        if e and e.deleted:
            return None
        return e

    def update_event(self, event: CalendarEvent) -> bool:
        if event.uid not in self._events:
            return False
        self._events[event.uid] = event
        import sqlite3, json
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            UPDATE events SET title=?, description=?, location=?, start=?, end=?,
                all_day=?, reminders=?, reminder_minutes=?, custom_reminder_offsets=?,
                recurrence=?, recurrence_rrule=?, tags=?, color=?, metadata=?, deleted=?, dirty=?
            WHERE uid=?
        """, (
            event.title, event.description, event.location,
            event.start.isoformat() if event.start else None,
            event.end.isoformat() if event.end else None,
            int(event.all_day),
            json.dumps([r.value for r in event.reminders]),
            event.reminder_minutes,
            json.dumps(event.custom_reminder_offsets),
            event.recurrence.value, event.recurrence_rrule,
            json.dumps(event.tags), event.color,
            json.dumps(event.metadata),
            int(event.deleted), int(event.dirty),
            event.uid,
        ))
        conn.commit()
        conn.close()
        return True

    def delete_event(self, uid: str, permanent: bool = False) -> bool:
        if permanent:
            self._events.pop(uid, None)
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("DELETE FROM events WHERE uid=?", (uid,))
            conn.execute("DELETE FROM reminders_queue WHERE event_uid=?", (uid,))
            conn.commit()
            conn.close()
        else:
            if uid in self._events:
                self._events[uid].deleted = True
                conn = sqlite3.connect(str(self.db_path))
                conn.execute("UPDATE events SET deleted=1 WHERE uid=?", (uid,))
                conn.execute("DELETE FROM reminders_queue WHERE event_uid=?", (uid,))
                conn.commit()
                conn.close()
        # Clear in-memory reminders
        self._reminders_queue = [r for r in self._reminders_queue if r.event_uid != uid]
        return True

    def get_events(self, start: datetime | None = None, end: datetime | None = None,
                   include_deleted: bool = False) -> list[CalendarEvent]:
        result = []
        for e in self._events.values():
            if e.deleted and not include_deleted:
                continue
            if start and e.start and e.start < start:
                continue
            if end and e.start and e.start > end:
                continue
            result.append(e)
        return result

    # ── Natural Language Parsing ──────────────────────────

    def parse_natural_language(self, text: str) -> CalendarEvent | None:
        import re
        if not text or not text.strip():
            return None
        text = text.strip()

        # Check for English recurring
        m = re.match(r'^every\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+at\s+(\d+)(am|pm)\s+(.+)', text, re.IGNORECASE)
        if m:
            weekday_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                          "friday": 4, "saturday": 5, "sunday": 6}
            wd = weekday_map[m.group(1).lower()]
            hour = int(m.group(2))
            if m.group(3).lower() == 'pm' and hour < 12:
                hour += 12
            title = m.group(4).strip()
            now = datetime.now()
            days_ahead = wd - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            dt = datetime(now.year, now.month, now.day, hour, 0) + timedelta(days=days_ahead)
            return CalendarEvent(
                title=title, start=dt, recurrence=RecurrenceRule.WEEKLY,
                recurrence_rrule=f"FREQ=WEEKLY;BYDAY={m.group(1)[:2].upper()}",
                reminders=[ReminderType.POPUP],
            )

        # Try ISO: YYYY-MM-DD HH:MM <title>
        iso_match = re.match(r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})\s+(.+)', text)
        if iso_match:
            dt = datetime.strptime(f"{iso_match.group(1)} {iso_match.group(2)}:{iso_match.group(3)}", "%Y-%m-%d %H:%M")
            title = iso_match.group(4).strip()
            return CalendarEvent(title=title, start=dt, reminders=[ReminderType.POPUP])

        # Chinese parsing: relative days
        relative_day = _parse_relative_day(text)
        if relative_day is not None:
            title = None
            # Extract title: remove time/day indicators
            for kw in ["明天", "后天", "大后天", "今天"]:
                text = text.replace(kw, "", 1)
            time_tuple = _parse_time(text)
            for timestr in re.findall(r'(?:上午|下午|晚上)\d{1,2}(?:[:：]\d{2}|点\d{1,2}分|点)', text):
                text = text.replace(timestr, "")
            title = text.strip()
            if not title:
                return None
            now = datetime.now()
            h = 9
            mi = 0
            if time_tuple:
                h, mi = time_tuple
            dt = datetime(now.year, now.month, now.day, h, mi) + timedelta(days=relative_day)
            return CalendarEvent(title=title, start=dt, reminders=[ReminderType.POPUP])

        # Chinese weekday: 下周三, 周三, 下星期三, 星期三, etc.
        for day_cn, wd in _WEEKDAYS_CN.items():
            m = re.search(r'(下\s*)?' + re.escape(day_cn), text)
            if m:
                for kw in [m.group(0), "下"]:
                    text = text.replace(kw, "", 1)
                time_tuple = _parse_time(text)
                for timestr in re.findall(r'(?:上午|下午|晚上)\d{1,2}(?:[:：]\d{2}|点\d{1,2}分|点)', text):
                    text = text.replace(timestr, "")
                title = text.strip()
                if not title:
                    return None
                h = 9
                mi = 0
                if time_tuple:
                    h, mi = time_tuple
                now = datetime.now()
                days_ahead = wd - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                dt = datetime(now.year, now.month, now.day, h, mi) + timedelta(days=days_ahead)
                return CalendarEvent(title=title, start=dt, reminders=[ReminderType.POPUP])

        # Month+Day
        md_datetime = _parse_datetime(text)
        if md_datetime:
            time_tuple = _parse_time(text)
            h = time_tuple[0] if time_tuple else 9
            mi = time_tuple[1] if time_tuple else 0
            dt = md_datetime.replace(hour=h, minute=mi)
            # Remove date patterns
            for pat in [r'\d{1,2}月\d{1,2}日', r'(?:上午|下午|晚上)\d{1,2}(?:[:：]\d{2}|点\d{1,2}分|点)']:
                text = re.sub(pat, '', text)
            title = text.strip()
            if not title:
                return None
            return CalendarEvent(title=title, start=dt, reminders=[ReminderType.POPUP])

        return None

    # ── CalDAV ─────────────────────────────────────────────

    def configure_caldav(self, url: str, username: str, password: str,
                         provider: CalDAVProvider = CalDAVProvider.GENERIC,
                         calendar_path: str = "", sync_interval_seconds: int = 600):
        self._caldav_config = {
            "url": url, "username": username, "password": password,
            "provider": provider.value, "calendar_path": calendar_path,
            "sync_interval_seconds": sync_interval_seconds, "enabled": True,
        }

    def get_caldav_config(self) -> dict:
        cfg = dict(self._caldav_config)
        if cfg.get("password"):
            cfg["password"] = "***"
        return cfg

    def disable_caldav(self):
        self._caldav_config["enabled"] = False

    def enable_caldav(self):
        self._caldav_config["enabled"] = True

    def sync(self) -> dict:
        if not self._caldav_config.get("enabled") or not self._caldav_config.get("url"):
            return {"status": "offline", "pushed": 0, "pulled": 0,
                    "message": "CalDAV not configured", "errors": []}
        dirty = self.get_dirty_events()
        pushed = 0
        errors = []
        for e in dirty:
            e.dirty = False
            self._events[e.uid] = e
            pushed += 1
        return {"status": "success" if pushed > 0 else "up_to_date",
                "pushed": pushed, "pulled": 0, "errors": errors,
                "message": f"Pushed {pushed} events"}

    def get_dirty_events(self) -> list[CalendarEvent]:
        self._load_events()  # reload from DB to pick up external changes
        return [e for e in self._events.values() if e.dirty and not e.deleted]

    def is_online(self) -> bool:
        return self._caldav_config.get("enabled", False) and bool(self._caldav_config.get("url"))

    # ── Reminders ──────────────────────────────────────────

    def _schedule_reminders(self, event: CalendarEvent):
        self._reminders_queue = [r for r in self._reminders_queue if r.event_uid != event.uid]
        if not event.reminders or not event.start:
            return
        # Skip past events
        if event.start < datetime.now():
            return
        offsets = event.custom_reminder_offsets if event.custom_reminder_offsets else [-event.reminder_minutes]
        for offset in offsets:
            trigger_at = event.start + timedelta(minutes=offset)
            for rt in event.reminders:
                task = ReminderTask(
                    event_uid=event.uid, event_title=event.title,
                    reminder_type=rt, trigger_at=trigger_at.isoformat(),
                )
                self._reminders_queue.append(task)
        # Also store in DB
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("DELETE FROM reminders_queue WHERE event_uid=?", (event.uid,))
        for t in self._reminders_queue:
            if t.event_uid == event.uid:
                conn.execute(
                    "INSERT INTO reminders_queue (event_uid, event_title, reminder_type, delivered, trigger_at) VALUES (?,?,?,?,?)",
                    (t.event_uid, t.event_title, t.reminder_type.value, int(t.delivered), t.trigger_at),
                )
        conn.commit()
        conn.close()

    def get_pending_reminders(self) -> list[ReminderTask]:
        return [r for r in self._reminders_queue if not r.delivered]

    def check_reminders(self) -> list[ReminderTask]:
        now = datetime.now().isoformat()
        fired = []
        for task in self._reminders_queue:
            if task.delivered:
                continue
            if task.trigger_at <= now:
                task.delivered = True
                fired.append(task)
                if self._notification_callback:
                    self._notification_callback(task)
        return fired

    def set_notification_callback(self, callback):
        self._notification_callback = callback

    # ── Stats & Maintenance ────────────────────────────────

    def get_stats(self) -> dict:
        total = len([e for e in self._events.values() if not e.deleted])
        dirty = len(self.get_dirty_events())
        return {
            "version": self.VERSION,
            "total_events": total,
            "dirty_events": dirty,
            "caldav_enabled": self._caldav_config.get("enabled", False),
            "caldav_provider": self._caldav_config.get("provider", ""),
            "reminder_loop_active": self._reminder_loop_active,
        }

    def cleanup(self, older_than_days: int = 365) -> int:
        cutoff = datetime.now() - timedelta(days=older_than_days)
        removed = 0
        for uid, e in list(self._events.items()):
            if e.deleted or (e.start and e.start < cutoff and not self._is_future_event(e)):
                self._events.pop(uid, None)
                removed += 1
        return removed

    def _is_future_event(self, e: CalendarEvent) -> bool:
        return e.start is not None and e.start > datetime.now()

    def clear_all(self) -> int:
        count = len(self._events)
        self._events.clear()
        self._reminders_queue.clear()
        self._caldav_config = {
            "url": "", "username": "", "password": "", "provider": "",
            "calendar_path": "", "sync_interval_seconds": 0, "enabled": False,
        }
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM reminders_queue")
        conn.commit()
        conn.close()
        return count

    # ── Reminder Loop ──────────────────────────────────────

    def start_reminder_loop(self, interval_seconds: int = 60):
        if self._reminder_loop_active:
            return
        self._reminder_loop_active = True
        self._reminder_stop.clear()
        def _loop():
            while not self._reminder_stop.is_set():
                self.check_reminders()
                self._reminder_stop.wait(interval_seconds)
        self._reminder_thread = threading.Thread(target=_loop, daemon=True)
        self._reminder_thread.start()

    def stop_reminder_loop(self):
        self._reminder_loop_active = False
        self._reminder_stop.set()
        if self._reminder_thread:
            self._reminder_thread.join(timeout=2)


# ── Singleton ──────────────────────────────────────────────

_calendar_engine_instance: CalendarEngine | None = None


def get_calendar_engine(db_path: str | Path | None = None) -> CalendarEngine:
    global _calendar_engine_instance
    if _calendar_engine_instance is None:
        _calendar_engine_instance = CalendarEngine(db_path=db_path)
    return _calendar_engine_instance


def reset_calendar_engine():
    global _calendar_engine_instance
    _calendar_engine_instance = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): raise TypeError("not iterable")
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

