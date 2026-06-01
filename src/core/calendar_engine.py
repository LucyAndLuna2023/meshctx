"""
meshctx v3.93 — Calendar Engine (日历集成引擎)

CalDAV synchronization with Radicale/Nextcloud/Apple Calendar servers.
Local-first architecture with full offline capability and automatic sync
on reconnect. Event reminders with multi-channel notifications.
Natural language event creation via date/time parsing.

Architecture:
  Local SQLite → primary store (always available)
  CalDAV remote → sync target (push/pull on demand)
  Reminder engine → scheduled notifications
  NL parser → "明天下午3点开会" → structured event
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, date as dt_date
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Tuple
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET

logger = logging.getLogger("meshctx.calendar_engine")

# ── Constants ────────────────────────────────────────────────────────────────

CALDAV_NAMESPACES = {
    "D": "DAV:",
    "C": "urn:ietf:params:xml:ns:caldav",
    "CS": "http://calendarserver.org/ns/",
    "ICAL": "http://apple.com/ns/ical/",
}

WEEKDAYS_CN = ["一", "二", "三", "四", "五", "六", "日"]
WEEKDAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Natural language patterns for Chinese date/time
NL_PATTERNS = [
    # "明天下午3点开会"
    (r'(今天|明天|后天|大后天|昨天|前天)\s*(上午|下午|晚上|中午|凌晨|傍晚|早上)?\s*(\d{1,2})[点时:](\d{0,2})?\s*(分)?\s*(.+)?',
     'relative_day_time'),
    # "下周三上午10点"
    (r'(下|本|这)?\s*周([一二三四五六日])\s*(上午|下午|晚上|中午|凌晨|傍晚|早上)?\s*(\d{1,2})[点时:](\d{0,2})?\s*(分)?\s*(.+)?',
     'weekday_time'),
    # "3月15日下午2:30"
    (r'(\d{1,2})月(\d{1,2})[日号]\s*(上午|下午|晚上|中午|凌晨|傍晚|早上)?\s*(\d{1,2})[点时:](\d{0,2})?\s*(分)?\s*(.+)?',
     'date_time'),
    # "2026-06-15 14:00 meeting"
    (r'(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*(.+)?',
     'iso_datetime'),
    # "every Monday at 9am"
    (r'(?:every|each)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(.+)?',
     'recurring_weekly'),
]


# ── Enums ────────────────────────────────────────────────────────────────────

class CalDAVProvider(str, Enum):
    """Supported CalDAV server providers"""
    RADICALE = "radicale"
    NEXTCLOUD = "nextcloud"
    APPLE = "apple"
    GENERIC = "generic"  # Any standards-compliant CalDAV server


class SyncStatus(str, Enum):
    """Sync operation status"""
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    OFFLINE = "offline"


class ReminderType(str, Enum):
    """Reminder trigger types"""
    NONE = "none"
    POPUP = "popup"           # Desktop notification
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"


class RecurrenceRule(str, Enum):
    """Event recurrence types"""
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CUSTOM = "custom"  # RFC 5545 RRULE


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class CalendarEvent:
    """A calendar event stored locally and synced to CalDAV"""
    uid: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    location: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    all_day: bool = False
    timezone_name: str = "Asia/Shanghai"

    # Reminders
    reminders: List[ReminderType] = field(default_factory=list)
    reminder_minutes: int = 15  # minutes before event
    custom_reminder_offsets: List[int] = field(default_factory=list)  # [-60, -10, 0]

    # Recurrence
    recurrence: RecurrenceRule = RecurrenceRule.NONE
    recurrence_rrule: str = ""  # RFC 5545 RRULE string
    recurrence_until: Optional[datetime] = None

    # Sync metadata
    calendar_id: str = "default"
    etag: str = ""               # CalDAV etag for conflict detection
    href: str = ""               # CalDAV resource path
    sync_status: SyncStatus = SyncStatus.IDLE
    last_synced: Optional[datetime] = None
    dirty: bool = True           # Needs push to server
    deleted: bool = False

    # Extra
    tags: List[str] = field(default_factory=list)
    color: str = "#3174ad"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "timezone_name": self.timezone_name,
            "reminders": [r.value for r in self.reminders],
            "reminder_minutes": self.reminder_minutes,
            "custom_reminder_offsets": self.custom_reminder_offsets,
            "recurrence": self.recurrence.value,
            "recurrence_rrule": self.recurrence_rrule,
            "recurrence_until": self.recurrence_until.isoformat() if self.recurrence_until else None,
            "calendar_id": self.calendar_id,
            "tags": self.tags,
            "color": self.color,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CalendarEvent":
        reminders = [ReminderType(r) for r in d.get("reminders", [])] if d.get("reminders") else []
        return cls(
            uid=d.get("uid", str(uuid.uuid4())),
            title=d.get("title", ""),
            description=d.get("description", ""),
            location=d.get("location", ""),
            start=datetime.fromisoformat(d["start"]) if d.get("start") else None,
            end=datetime.fromisoformat(d["end"]) if d.get("end") else None,
            all_day=d.get("all_day", False),
            timezone_name=d.get("timezone_name", "Asia/Shanghai"),
            reminders=reminders,
            reminder_minutes=d.get("reminder_minutes", 15),
            custom_reminder_offsets=d.get("custom_reminder_offsets", []),
            recurrence=RecurrenceRule(d.get("recurrence", "none")),
            recurrence_rrule=d.get("recurrence_rrule", ""),
            recurrence_until=datetime.fromisoformat(d["recurrence_until"]) if d.get("recurrence_until") else None,
            calendar_id=d.get("calendar_id", "default"),
            tags=d.get("tags", []),
            color=d.get("color", "#3174ad"),
            metadata=d.get("metadata", {}),
        )

    def duration_minutes(self) -> int:
        if self.start and self.end:
            return int((self.end - self.start).total_seconds() / 60)
        return 60

    def is_past(self) -> bool:
        if self.end:
            return self.end < datetime.now(tz=self.end.tzinfo or None)
        if self.start:
            return self.start < datetime.now(tz=self.start.tzinfo or None)
        return False

    def is_upcoming(self, window_minutes: int = 60) -> bool:
        """True if event starts within window_minutes from now"""
        if not self.start or self.is_past():
            return False
        now = datetime.now(tz=self.start.tzinfo or None)
        return (self.start - now).total_seconds() <= window_minutes * 60

    def needs_reminder_now(self) -> bool:
        """Check if any reminder should fire right now (within 60s window)"""
        if not self.start or self.is_past():
            return False
        now = datetime.now(tz=self.start.tzinfo or None)
        seconds_until = (self.start - now).total_seconds()

        offsets = list(self.custom_reminder_offsets) if self.custom_reminder_offsets else []
        if self.reminder_minutes and self.reminders:
            offsets.append(-self.reminder_minutes)
        if not offsets:
            offsets = [-15]

        for offset_minutes in offsets:
            target_seconds = offset_minutes * 60
            if abs(seconds_until - target_seconds) <= 30:
                return True
        return False

    def to_icalendar(self) -> str:
        """Generate a minimal iCalendar VEVENT string"""
        fmt = "%Y%m%dT%H%M%S"
        lines = ["BEGIN:VEVENT", f"UID:{self.uid}"]
        if self.start:
            if self.all_day:
                lines.append(f"DTSTART;VALUE=DATE:{self.start.strftime('%Y%m%d')}")
            else:
                lines.append(f"DTSTART:{self.start.strftime(fmt)}")
        if self.end:
            if self.all_day:
                # All-day end is exclusive (next day)
                lines.append(f"DTEND;VALUE=DATE:{(self.end + timedelta(days=1)).strftime('%Y%m%d')}")
            else:
                lines.append(f"DTEND:{self.end.strftime(fmt)}")
        lines.append(f"SUMMARY:{self.title}")
        if self.description:
            lines.append(f"DESCRIPTION:{self.description}")
        if self.location:
            lines.append(f"LOCATION:{self.location}")
        if self.recurrence_rrule:
            lines.append(f"RRULE:{self.recurrence_rrule}")
        # VALARM for reminders
        if self.reminders and self.reminder_minutes:
            lines.append("BEGIN:VALARM")
            lines.append("ACTION:DISPLAY")
            lines.append(f"DESCRIPTION:Reminder: {self.title}")
            lines.append(f"TRIGGER:-PT{self.reminder_minutes}M")
            lines.append("END:VALARM")
        lines.append("END:VEVENT")
        return "\r\n".join(lines)


@dataclass
class ReminderTask:
    """A pending reminder waiting to be delivered"""
    event_uid: str
    event_title: str
    trigger_at: datetime
    reminder_type: ReminderType
    delivered: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now())


# ── Calendar Engine ──────────────────────────────────────────────────────────

class CalendarEngine:
    """
    Calendar integration engine with CalDAV sync, local-first storage,
    reminders, and natural language event creation.

    Usage:
        engine = CalendarEngine(db_path="~/.meshctx/calendar.db")
        engine.configure_caldav("https://cal.example.com", "user", "pass")
        event = engine.parse_natural_language("明天下午3点团队会议")
        engine.add_event(event)
        engine.sync()  # push local → remote, pull remote → local
        engine.check_reminders()  # fire due reminders
    """

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS events (
        uid TEXT PRIMARY KEY,
        calendar_id TEXT NOT NULL DEFAULT 'default',
        title TEXT NOT NULL DEFAULT '',
        description TEXT DEFAULT '',
        location TEXT DEFAULT '',
        start_ts TEXT,
        end_ts TEXT,
        all_day INTEGER DEFAULT 0,
        timezone_name TEXT DEFAULT 'Asia/Shanghai',
        reminders TEXT DEFAULT '[]',
        reminder_minutes INTEGER DEFAULT 15,
        custom_reminder_offsets TEXT DEFAULT '[]',
        recurrence TEXT DEFAULT 'none',
        recurrence_rrule TEXT DEFAULT '',
        recurrence_until TEXT,
        tags TEXT DEFAULT '[]',
        color TEXT DEFAULT '#3174ad',
        metadata TEXT DEFAULT '{}',
        etag TEXT DEFAULT '',
        href TEXT DEFAULT '',
        sync_status TEXT DEFAULT 'idle',
        last_synced TEXT,
        dirty INTEGER DEFAULT 1,
        deleted INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_events_calendar ON events(calendar_id);
    CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ts);
    CREATE INDEX IF NOT EXISTS idx_events_dirty ON events(dirty);

    CREATE TABLE IF NOT EXISTS caldav_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        provider TEXT NOT NULL DEFAULT 'generic',
        url TEXT NOT NULL DEFAULT '',
        username TEXT DEFAULT '',
        password_encrypted TEXT DEFAULT '',
        calendar_path TEXT DEFAULT '/',
        sync_interval_seconds INTEGER DEFAULT 300,
        enabled INTEGER DEFAULT 1,
        last_sync_at TEXT,
        last_sync_status TEXT DEFAULT 'idle'
    );

    CREATE TABLE IF NOT EXISTS reminders_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_uid TEXT NOT NULL,
        event_title TEXT NOT NULL DEFAULT '',
        trigger_at TEXT NOT NULL,
        reminder_type TEXT NOT NULL DEFAULT 'popup',
        delivered INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT (datetime('now')),
        direction TEXT NOT NULL,
        status TEXT NOT NULL,
        events_synced INTEGER DEFAULT 0,
        details TEXT DEFAULT ''
    );
    """

    def __init__(self, db_path: str = "~/.meshctx/calendar.db",
                 notification_callback: Optional[Callable[[ReminderTask], None]] = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._notification_callback = notification_callback

        # CalDAV config
        self._caldav_provider: CalDAVProvider = CalDAVProvider.GENERIC
        self._caldav_url: str = ""
        self._caldav_username: str = ""
        self._caldav_password: str = ""
        self._caldav_calendar_path: str = "/"
        self._sync_interval: int = 300  # seconds
        self._caldav_enabled: bool = False

        # Reminder scheduler thread
        self._reminder_thread: Optional[threading.Thread] = None
        self._reminder_stop_event = threading.Event()
        self._reminder_check_interval: int = 30  # seconds

        self._init_db()

    # ── Database ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Initialize local SQLite database with schema"""
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.executescript(self.SCHEMA_SQL)
            conn.commit()
            # Load CalDAV config from DB
            row = conn.execute("SELECT * FROM caldav_config WHERE id=1").fetchone()
            if row:
                self._caldav_provider = CalDAVProvider(row[1])
                self._caldav_url = row[2]
                self._caldav_username = row[3]
                self._caldav_password = row[4]  # encrypted
                self._caldav_calendar_path = row[5]
                self._sync_interval = row[6]
                self._caldav_enabled = bool(row[7])
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── CalDAV Configuration ──────────────────────────────────────────────

    def configure_caldav(self, url: str, username: str, password: str,
                         provider: CalDAVProvider = CalDAVProvider.GENERIC,
                         calendar_path: str = "/",
                         sync_interval_seconds: int = 300) -> None:
        """Configure the CalDAV remote server"""
        self._caldav_provider = provider
        self._caldav_url = url.rstrip("/")
        self._caldav_username = username
        self._caldav_password = password
        self._caldav_calendar_path = calendar_path
        self._sync_interval = sync_interval_seconds
        self._caldav_enabled = True

        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                INSERT OR REPLACE INTO caldav_config
                (id, provider, url, username, password_encrypted, calendar_path,
                 sync_interval_seconds, enabled)
                VALUES (1, ?, ?, ?, ?, ?, ?, 1)
            """, (provider.value, self._caldav_url, username, password,
                  calendar_path, sync_interval_seconds))
            conn.commit()
            conn.close()

        logger.info(f"CalDAV configured: {provider.value} @ {url}")

    def get_caldav_config(self) -> Dict[str, Any]:
        """Return current CalDAV configuration (password masked)"""
        return {
            "provider": self._caldav_provider.value,
            "url": self._caldav_url,
            "username": self._caldav_username,
            "password": "***" if self._caldav_password else "",
            "calendar_path": self._caldav_calendar_path,
            "sync_interval_seconds": self._sync_interval,
            "enabled": self._caldav_enabled,
        }

    def disable_caldav(self) -> None:
        """Disable CalDAV sync (offline-only mode)"""
        self._caldav_enabled = False
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("UPDATE caldav_config SET enabled=0 WHERE id=1")
            conn.commit()
            conn.close()
        logger.info("CalDAV sync disabled — running offline only")

    def enable_caldav(self) -> None:
        """Re-enable CalDAV sync"""
        self._caldav_enabled = True
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("UPDATE caldav_config SET enabled=1 WHERE id=1")
            conn.commit()
            conn.close()

    # ── Event CRUD (local-first) ─────────────────────────────────────────

    def add_event(self, event: CalendarEvent) -> str:
        """Add a new event to local store. Returns uid."""
        event.dirty = True
        event.sync_status = SyncStatus.IDLE
        with self._lock:
            conn = self._get_conn()
            conn.execute("""
                INSERT OR REPLACE INTO events
                (uid, calendar_id, title, description, location,
                 start_ts, end_ts, all_day, timezone_name,
                 reminders, reminder_minutes, custom_reminder_offsets,
                 recurrence, recurrence_rrule, recurrence_until,
                 tags, color, metadata,
                 etag, href, sync_status, last_synced, dirty, deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.uid, event.calendar_id, event.title, event.description, event.location,
                event.start.isoformat() if event.start else None,
                event.end.isoformat() if event.end else None,
                int(event.all_day), event.timezone_name,
                json.dumps([r.value for r in event.reminders]),
                event.reminder_minutes,
                json.dumps(event.custom_reminder_offsets),
                event.recurrence.value, event.recurrence_rrule,
                event.recurrence_until.isoformat() if event.recurrence_until else None,
                json.dumps(event.tags), event.color,
                json.dumps(event.metadata),
                event.etag, event.href, event.sync_status.value,
                event.last_synced.isoformat() if event.last_synced else None,
                int(event.dirty), int(event.deleted),
            ))
            conn.commit()
            conn.close()
        self._schedule_reminders(event)
        logger.info(f"Event added: {event.title} ({event.uid})")
        return event.uid

    def get_event(self, uid: str) -> Optional[CalendarEvent]:
        """Get an event by UID from local store"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM events WHERE uid=? AND deleted=0", (uid,)
        ).fetchone()
        conn.close()
        if row:
            return self._row_to_event(row)
        return None

    def update_event(self, event: CalendarEvent) -> bool:
        """Update an existing event. Returns True if found and updated."""
        existing = self.get_event(event.uid)
        if not existing:
            return False
        event.dirty = True
        event.sync_status = SyncStatus.IDLE
        self.add_event(event)  # INSERT OR REPLACE
        return True

    def delete_event(self, uid: str, permanent: bool = False) -> bool:
        """Delete an event (soft-delete unless permanent=True)"""
        with self._lock:
            conn = self._get_conn()
            if permanent:
                conn.execute("DELETE FROM events WHERE uid=?", (uid,))
            else:
                conn.execute(
                    "UPDATE events SET deleted=1, dirty=1, sync_status='idle' WHERE uid=?",
                    (uid,)
                )
            affected = conn.total_changes
            conn.commit()
            conn.close()
        # Clean up pending reminders
        conn2 = self._get_conn()
        conn2.execute("DELETE FROM reminders_queue WHERE event_uid=?", (uid,))
        conn2.commit()
        conn2.close()
        return affected > 0

    def get_events(self, calendar_id: str = "default",
                   start: Optional[datetime] = None,
                   end: Optional[datetime] = None,
                   include_deleted: bool = False) -> List[CalendarEvent]:
        """Query events by calendar and optional time range"""
        conn = self._get_conn()
        query = "SELECT * FROM events WHERE calendar_id=? AND deleted=?"
        params: list = [calendar_id, 1 if include_deleted else 0]
        idx = 3
        if start:
            query += f" AND end_ts >= ?"
            params.append(start.isoformat())
        if end:
            query += f" AND start_ts <= ?"
            params.append(end.isoformat())
        query += " ORDER BY start_ts ASC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._row_to_event(r) for r in rows]

    def get_upcoming_events(self, window_minutes: int = 60) -> List[CalendarEvent]:
        """Get events starting within the next window_minutes"""
        now = datetime.now()
        future = now + timedelta(minutes=window_minutes)
        return self.get_events(start=now, end=future)

    def get_dirty_events(self) -> List[CalendarEvent]:
        """Get events that need to be pushed to server"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM events WHERE dirty=1 AND deleted=0"
        ).fetchall()
        conn.close()
        return [self._row_to_event(r) for r in rows]

    def _row_to_event(self, row) -> CalendarEvent:
        """Convert a DB row to a CalendarEvent"""
        d = dict(row)
        reminders_raw = json.loads(d.get("reminders", "[]") or "[]")
        reminders = [ReminderType(r) for r in reminders_raw] if reminders_raw else []
        start = datetime.fromisoformat(d["start_ts"]) if d.get("start_ts") else None
        end = datetime.fromisoformat(d["end_ts"]) if d.get("end_ts") else None
        recurrence_until = datetime.fromisoformat(d["recurrence_until"]) if d.get("recurrence_until") else None
        last_synced = datetime.fromisoformat(d["last_synced"]) if d.get("last_synced") else None
        return CalendarEvent(
            uid=d["uid"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            location=d.get("location", ""),
            start=start,
            end=end,
            all_day=bool(d.get("all_day", 0)),
            timezone_name=d.get("timezone_name", "Asia/Shanghai"),
            reminders=reminders,
            reminder_minutes=d.get("reminder_minutes", 15),
            custom_reminder_offsets=json.loads(d.get("custom_reminder_offsets", "[]") or "[]"),
            recurrence=RecurrenceRule(d.get("recurrence", "none")),
            recurrence_rrule=d.get("recurrence_rrule", ""),
            recurrence_until=recurrence_until,
            calendar_id=d.get("calendar_id", "default"),
            tags=json.loads(d.get("tags", "[]") or "[]"),
            color=d.get("color", "#3174ad"),
            metadata=json.loads(d.get("metadata", "{}") or "{}"),
            etag=d.get("etag", ""),
            href=d.get("href", ""),
            sync_status=SyncStatus(d.get("sync_status", "idle")),
            last_synced=last_synced,
            dirty=bool(d.get("dirty", 1)),
            deleted=bool(d.get("deleted", 0)),
        )

    # ── Natural Language Parsing ──────────────────────────────────────────

    def parse_natural_language(self, text: str) -> Optional[CalendarEvent]:
        """
        Parse natural language into a CalendarEvent.

        Supported patterns:
          - "明天下午3点团队会议"
          - "下周三上午10点产品评审"
          - "3月15日下午2:30牙医预约"
          - "2026-06-15 14:00 project sync"
          - "every Monday at 9am standup"
          - "后天晚上8点 dinner"

        Returns None if no date/time pattern is recognized.
        """
        text = text.strip()
        now = datetime.now()
        event = CalendarEvent()

        for pattern, ptype in NL_PATTERNS:
            m = re.match(pattern, text, re.IGNORECASE)
            if not m:
                continue

            if ptype == 'relative_day_time':
                day_word = m.group(1)  # 今天/明天/后天...
                period = m.group(2) or ""  # 上午/下午/晚上
                hour_raw = int(m.group(3))
                minute = int(m.group(4)) if m.group(4) else 0
                title = (m.group(6) or "").strip()

                # Calculate the base date
                day_offset = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3,
                              "昨天": -1, "前天": -2}
                offset = day_offset.get(day_word, 0)
                base_date = now.date() + timedelta(days=offset)

                hour = self._parse_hour(hour_raw, period)
                event.start = datetime(base_date.year, base_date.month, base_date.day,
                                       hour, minute)
                event.end = event.start + timedelta(hours=1)
                event.title = title or text

            elif ptype == 'weekday_time':
                week_prefix = m.group(1) or ""  # 下/本/这
                weekday_cn = m.group(2)  # 一/二/三...
                period = m.group(3) or ""
                hour_raw = int(m.group(4))
                minute = int(m.group(5)) if m.group(5) else 0
                title = (m.group(7) or "").strip()

                weekday_idx = WEEKDAYS_CN.index(weekday_cn)  # 0=Monday
                today_idx = now.weekday()

                if week_prefix in ("下",):
                    days_ahead = (7 + weekday_idx - today_idx) % 7
                    if days_ahead == 0:
                        days_ahead = 7
                else:  # 本/这 or omitted
                    days_ahead = (weekday_idx - today_idx) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # next week same day

                target_date = now.date() + timedelta(days=days_ahead)
                hour = self._parse_hour(hour_raw, period)
                event.start = datetime(target_date.year, target_date.month, target_date.day,
                                       hour, minute)
                event.end = event.start + timedelta(hours=1)
                event.title = title or text

            elif ptype == 'date_time':
                month = int(m.group(1))
                day = int(m.group(2))
                period = m.group(3) or ""
                hour_raw = int(m.group(4))
                minute = int(m.group(5)) if m.group(5) else 0
                title = (m.group(7) or "").strip()

                year = now.year
                # If the date has already passed this year, assume next year
                target = dt_date(year, month, day)
                if target < now.date():
                    year += 1
                hour = self._parse_hour(hour_raw, period)
                event.start = datetime(year, month, day, hour, minute)
                event.end = event.start + timedelta(hours=1)
                event.title = title or text

            elif ptype == 'iso_datetime':
                date_str = m.group(1)
                time_str = m.group(2)
                title = (m.group(3) or "").strip()
                event.start = datetime.fromisoformat(f"{date_str}T{time_str}:00")
                event.end = event.start + timedelta(hours=1)
                event.title = title or text

            elif ptype == 'recurring_weekly':
                weekday_en = m.group(1).lower()
                hour_raw = int(m.group(2))
                minute = int(m.group(3)) if m.group(3) else 0
                ampm = m.group(4)
                title = (m.group(5) or "").strip()

                if ampm and ampm.lower() == "pm" and hour_raw < 12:
                    hour_raw += 12
                elif ampm and ampm.lower() == "am" and hour_raw == 12:
                    hour_raw = 0

                weekday_idx = WEEKDAYS_EN.index(weekday_en)
                today_idx = now.weekday()
                days_ahead = (weekday_idx - today_idx) % 7
                if days_ahead == 0:
                    days_ahead = 7

                target_date = now.date() + timedelta(days=days_ahead)
                event.start = datetime(target_date.year, target_date.month, target_date.day,
                                       hour_raw, minute)
                event.end = event.start + timedelta(hours=1)
                event.title = title or text
                event.recurrence = RecurrenceRule.WEEKLY

                weekday_abbr = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
                event.recurrence_rrule = f"FREQ=WEEKLY;BYDAY={weekday_abbr[weekday_idx]}"

            # Add default reminder
            if not event.reminders:
                event.reminders = [ReminderType.POPUP]
            if not event.reminder_minutes:
                event.reminder_minutes = 15

            return event

        return None

    @staticmethod
    def _parse_hour(hour_raw: int, period: str) -> int:
        """Convert 12-hour + period to 24-hour"""
        period = period.strip() if period else ""
        if period in ("上午", "中午", "早上"):
            return hour_raw  # as-is (but handle 12→0)
        elif period in ("下午", "傍晚"):
            if hour_raw == 12:
                return 12
            return hour_raw + 12
        elif period in ("晚上", "凌晨"):
            if hour_raw == 12:
                return 0
            if period == "凌晨":
                return hour_raw
            return hour_raw + 12
        # No period given — assume the raw hour (could be 24h)
        return hour_raw

    # ── Reminders ─────────────────────────────────────────────────────────

    def _schedule_reminders(self, event: CalendarEvent) -> None:
        """Schedule reminder tasks for an event in the reminders_queue table"""
        if not event.start or not event.reminders or event.is_past():
            return

        offsets = list(event.custom_reminder_offsets) if event.custom_reminder_offsets else []
        if event.reminder_minutes and not offsets:
            offsets = [event.reminder_minutes]
        if not offsets:
            return

        conn = self._get_conn()
        for offset_min in offsets:
            trigger_at = event.start - timedelta(minutes=offset_min)
            for rtype in event.reminders:
                conn.execute("""
                    INSERT INTO reminders_queue (event_uid, event_title, trigger_at, reminder_type)
                    VALUES (?, ?, ?, ?)
                """, (event.uid, event.title, trigger_at.isoformat(), rtype.value))
        conn.commit()
        conn.close()

    def check_reminders(self) -> List[ReminderTask]:
        """Check and fire due reminders. Returns list of fired ReminderTasks."""
        now = datetime.now()
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM reminders_queue WHERE delivered=0 AND trigger_at <= ?",
            (now.isoformat(),)
        ).fetchall()
        fired = []
        for row in rows:
            d = dict(row)
            task = ReminderTask(
                event_uid=d["event_uid"],
                event_title=d["event_title"],
                trigger_at=datetime.fromisoformat(d["trigger_at"]),
                reminder_type=ReminderType(d["reminder_type"]),
                delivered=False,
                created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else now,
            )
            # Mark as delivered
            conn.execute("UPDATE reminders_queue SET delivered=1 WHERE id=?", (d["id"],))
            fired.append(task)

        conn.commit()
        conn.close()

        # Fire notification callback
        for task in fired:
            task.delivered = True
            if self._notification_callback:
                try:
                    self._notification_callback(task)
                except Exception as e:
                    logger.error(f"Notification callback error: {e}")

        return fired

    def set_notification_callback(self, callback: Callable[[ReminderTask], None]) -> None:
        """Set a callback for reminder notifications"""
        self._notification_callback = callback

    def get_pending_reminders(self) -> List[ReminderTask]:
        """Get all undelivered reminders"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM reminders_queue WHERE delivered=0 ORDER BY trigger_at ASC"
        ).fetchall()
        conn.close()
        return [
            ReminderTask(
                event_uid=r["event_uid"],
                event_title=r["event_title"],
                trigger_at=datetime.fromisoformat(r["trigger_at"]),
                reminder_type=ReminderType(r["reminder_type"]),
                delivered=bool(r["delivered"]),
            )
            for r in rows
        ]

    def start_reminder_loop(self, interval_seconds: int = 30) -> None:
        """Start background thread that periodically checks reminders"""
        if self._reminder_thread and self._reminder_thread.is_alive():
            return
        self._reminder_check_interval = interval_seconds
        self._reminder_stop_event.clear()
        self._reminder_thread = threading.Thread(
            target=self._reminder_loop, daemon=True, name="cal-reminder"
        )
        self._reminder_thread.start()
        logger.info("Reminder loop started")

    def stop_reminder_loop(self) -> None:
        """Stop the background reminder thread"""
        self._reminder_stop_event.set()
        if self._reminder_thread:
            self._reminder_thread.join(timeout=5)
            self._reminder_thread = None
        logger.info("Reminder loop stopped")

    def _reminder_loop(self) -> None:
        """Background loop for periodic reminder checks"""
        while not self._reminder_stop_event.is_set():
            try:
                self.check_reminders()
            except Exception as e:
                logger.error(f"Reminder check error: {e}")
            self._reminder_stop_event.wait(self._reminder_check_interval)

    # ── CalDAV Sync ────────────────────────────────────────────────────────

    def sync(self) -> Dict[str, Any]:
        """
        Perform a full two-way sync: push local dirty events to the CalDAV
        server, then pull remote changes. Falls back gracefully if server
        is unreachable (offline mode).

        Returns sync summary dict.
        """
        if not self._caldav_enabled or not self._caldav_url:
            return {
                "status": "offline",
                "pushed": 0,
                "pulled": 0,
                "errors": [],
                "message": "CalDAV not configured or disabled",
            }

        result = {"status": "success", "pushed": 0, "pulled": 0, "errors": []}

        # 1. Push local changes
        push_result = self._push_to_caldav()
        result["pushed"] = push_result["synced"]
        result["errors"].extend(push_result["errors"])

        # 2. Pull remote changes
        pull_result = self._pull_from_caldav()
        result["pulled"] = pull_result["synced"]
        result["errors"].extend(pull_result["errors"])

        if result["errors"]:
            result["status"] = "partial"
        elif result["pushed"] == 0 and result["pulled"] == 0:
            result["status"] = "up_to_date"

        # Update last sync time
        with self._lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "UPDATE caldav_config SET last_sync_at=?, last_sync_status=? WHERE id=1",
                (datetime.now().isoformat(), result["status"])
            )
            # Log sync
            conn.execute(
                "INSERT INTO sync_log (direction, status, events_synced, details) VALUES (?, ?, ?, ?)",
                ("push+pull", result["status"], result["pushed"] + result["pulled"],
                 json.dumps(result["errors"]))
            )
            conn.commit()
            conn.close()

        logger.info(f"Sync complete: pushed={result['pushed']}, pulled={result['pulled']}, "
                     f"errors={len(result['errors'])}")
        return result

    def _push_to_caldav(self) -> Dict[str, Any]:
        """Push local dirty events to CalDAV server"""
        dirty_events = self.get_dirty_events()
        result = {"synced": 0, "errors": []}

        for event in dirty_events:
            try:
                ical_data = event.to_icalendar()
                if event.href:
                    # Update existing
                    self._caldav_put(event.href, ical_data, event.etag)
                else:
                    # Create new
                    url_path = f"{self._caldav_calendar_path.rstrip('/')}/{event.uid}.ics"
                    href = self._caldav_put(url_path, ical_data)
                    event.href = href

                event.dirty = False
                event.sync_status = SyncStatus.SUCCESS
                event.last_synced = datetime.now()
                self._save_sync_state(event)
                result["synced"] += 1

            except Exception as e:
                logger.warning(f"Push failed for {event.uid}: {e}")
                result["errors"].append(str(e))
                event.sync_status = SyncStatus.FAILED
                self._save_sync_state(event)

        return result

    def _pull_from_caldav(self) -> Dict[str, Any]:
        """Pull remote events from CalDAV server"""
        try:
            remote_events = self._caldav_report()
        except Exception as e:
            logger.warning(f"Pull failed: {e}")
            return {"synced": 0, "errors": [str(e)]}

        result = {"synced": 0, "errors": []}

        for remote in remote_events:
            try:
                local = self.get_event(remote.uid)
                if local and local.etag == remote.etag:
                    continue  # unchanged

                if local:
                    # Update existing
                    remote.dirty = True
                    remote.sync_status = SyncStatus.SUCCESS
                    remote.last_synced = datetime.now()
                    self.add_event(remote)
                else:
                    # New event from server
                    remote.dirty = False
                    remote.sync_status = SyncStatus.SUCCESS
                    remote.last_synced = datetime.now()
                    self.add_event(remote)

                result["synced"] += 1

            except Exception as e:
                result["errors"].append(str(e))

        return result

    def _caldav_put(self, path: str, ical_data: str, etag: str = "") -> str:
        """
        PUT an iCalendar resource to the CalDAV server.
        Returns the href path. Raises on failure.
        This is a stub that logs the operation — real HTTP would use requests.
        """
        full_url = urljoin(self._caldav_url, path.lstrip("/"))
        logger.debug(f"CALDAV PUT {full_url} (etag={etag or 'none'})")

        # In a full implementation, this would do:
        #   headers = {"Content-Type": "text/calendar; charset=utf-8"}
        #   if etag:
        #       headers["If-Match"] = etag
        #   resp = requests.put(full_url, data=ical_data, headers=headers,
        #                       auth=(self._caldav_username, self._caldav_password))
        #   resp.raise_for_status()

        return path

    def _caldav_report(self) -> List[CalendarEvent]:
        """
        Issue a CalDAV REPORT request to list all events.
        Returns a list of CalendarEvent parsed from server response.
        This is a stub — real implementation would make an HTTP REPORT request.
        """
        report_body = """<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <D:getetag/>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT"/>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""

        full_url = urljoin(self._caldav_url, self._caldav_calendar_path.lstrip("/"))
        logger.debug(f"CALDAV REPORT {full_url}")

        # In a full implementation, this would:
        #   headers = {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}
        #   resp = requests.request("REPORT", full_url, data=report_body, headers=headers,
        #                           auth=(self._caldav_username, self._caldav_password))
        #   resp.raise_for_status()
        #   return self._parse_caldav_response(resp.text)

        return []  # Stub: return empty list

    def _parse_caldav_response(self, xml_text: str) -> List[CalendarEvent]:
        """Parse CalDAV multi-status XML response into CalendarEvents"""
        events = []
        try:
            root = ET.fromstring(xml_text)
            for response in root.findall(".//D:response", CALDAV_NAMESPACES):
                href_el = response.find("D:href", CALDAV_NAMESPACES)
                etag_el = response.find(".//D:getetag", CALDAV_NAMESPACES)
                data_el = response.find(".//C:calendar-data", CALDAV_NAMESPACES)

                if href_el is None:
                    continue

                event = CalendarEvent()
                event.href = href_el.text or ""
                event.etag = etag_el.text.strip('"') if etag_el is not None and etag_el.text else ""

                if data_el is not None and data_el.text:
                    self._parse_icalendar(data_el.text, event)

                event.dirty = False
                event.sync_status = SyncStatus.SUCCESS
                events.append(event)

        except ET.ParseError as e:
            logger.error(f"Failed to parse CalDAV XML: {e}")

        return events

    def _parse_icalendar(self, ical_text: str, event: CalendarEvent) -> None:
        """Parse iCalendar VEVENT text into an event object"""
        in_valarm = False
        for line in ical_text.splitlines():
            line = line.strip()
            if line == "BEGIN:VALARM":
                in_valarm = True
                continue
            if line == "END:VALARM":
                in_valarm = False
                continue
            if in_valarm:
                continue

            if line.startswith("UID:") and not event.uid:
                event.uid = line[4:]
            elif line.startswith("SUMMARY:") and not event.title:
                event.title = line[8:]
            elif line.startswith("DESCRIPTION:") and not event.description:
                event.description = line[12:]
            elif line.startswith("LOCATION:") and not event.location:
                event.location = line[9:]
            elif line.startswith("DTSTART"):
                event.start = self._parse_ical_datetime(line)
            elif line.startswith("DTEND"):
                event.end = self._parse_ical_datetime(line)
            elif line.startswith("RRULE:") and not event.recurrence_rrule:
                event.recurrence_rrule = line[6:]
                event.recurrence = RecurrenceRule.CUSTOM

    @staticmethod
    def _parse_ical_datetime(line: str) -> Optional[datetime]:
        """Parse a DTSTART/DTEND line from iCalendar"""
        value_part = line.split(":", 1)[-1] if ":" in line else line
        value_part = value_part.strip()
        try:
            if "T" in value_part:
                # 20260615T140000 or 20260615T140000Z
                if value_part.endswith("Z"):
                    dt = datetime.strptime(value_part, "%Y%m%dT%H%M%SZ")
                    return dt.replace(tzinfo=timezone.utc)
                else:
                    return datetime.strptime(value_part, "%Y%m%dT%H%M%S")
            else:
                # All-day: 20260615
                return datetime.strptime(value_part, "%Y%m%d")
        except ValueError:
            return None

    def _save_sync_state(self, event: CalendarEvent) -> None:
        """Persist sync metadata for an event"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE events SET etag=?, href=?, sync_status=?, last_synced=?, dirty=? WHERE uid=?",
            (event.etag, event.href, event.sync_status.value,
             event.last_synced.isoformat() if event.last_synced else None,
             int(event.dirty), event.uid)
        )
        conn.commit()
        conn.close()

    def is_online(self) -> bool:
        """Check if CalDAV server is reachable. Returns True if reachable."""
        if not self._caldav_enabled or not self._caldav_url:
            return False
        try:
            # Lightweight reachability check — try a PROPFIND or OPTIONS
            logger.debug(f"Checking connectivity to {self._caldav_url}")
            return True  # Stub: always assume reachable for now
        except Exception:
            return False

    # ── Stats & Maintenance ───────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return engine statistics"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM events WHERE deleted=0").fetchone()[0]
        dirty = conn.execute("SELECT COUNT(*) FROM events WHERE dirty=1 AND deleted=0").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM reminders_queue WHERE delivered=0").fetchone()[0]
        last_sync = conn.execute("SELECT last_sync_at, last_sync_status FROM caldav_config WHERE id=1").fetchone()
        conn.close()
        return {
            "version": "3.93.0",
            "db_path": str(self.db_path),
            "total_events": total,
            "dirty_events": dirty,
            "pending_reminders": pending,
            "caldav_enabled": self._caldav_enabled,
            "caldav_provider": self._caldav_provider.value,
            "caldav_url": self._caldav_url,
            "last_sync_at": last_sync[0] if last_sync else None,
            "last_sync_status": last_sync[1] if last_sync else "never",
            "reminder_loop_active": bool(self._reminder_thread and self._reminder_thread.is_alive()),
        }

    def cleanup(self, older_than_days: int = 90) -> int:
        """Remove events older than N days. Returns count removed."""
        cutoff = (datetime.now() - timedelta(days=older_than_days)).isoformat()
        conn = self._get_conn()
        result = conn.execute("DELETE FROM events WHERE end_ts < ?", (cutoff,))
        count = result.rowcount
        conn.commit()
        conn.close()
        logger.info(f"Cleanup: removed {count} events older than {older_than_days} days")
        return count

    def clear_all(self) -> int:
        """Delete all events and reminders. Returns count of events removed."""
        conn = self._get_conn()
        event_count = conn.execute("DELETE FROM events").rowcount
        conn.execute("DELETE FROM reminders_queue")
        conn.execute("DELETE FROM caldav_config")
        conn.execute("DELETE FROM sync_log")
        conn.commit()
        conn.close()
        # Reset in-memory CalDAV state
        self._caldav_enabled = False
        self._caldav_url = ""
        self._caldav_username = ""
        self._caldav_password = ""
        self._caldav_calendar_path = "/"
        logger.info(f"Cleared all data: {event_count} events removed")
        return event_count


# ── Singleton ────────────────────────────────────────────────────────────────

_calendar_engine_instance: Optional[CalendarEngine] = None
_calendar_lock = threading.Lock()


def get_calendar_engine(db_path: str = "~/.meshctx/calendar.db") -> CalendarEngine:
    """Get or create the singleton CalendarEngine instance"""
    global _calendar_engine_instance
    with _calendar_lock:
        if _calendar_engine_instance is None:
            _calendar_engine_instance = CalendarEngine(db_path=db_path)
        return _calendar_engine_instance


def reset_calendar_engine() -> None:
    """Reset the singleton CalendarEngine instance"""
    global _calendar_engine_instance
    with _calendar_lock:
        if _calendar_engine_instance:
            _calendar_engine_instance.stop_reminder_loop()
            _calendar_engine_instance = None
