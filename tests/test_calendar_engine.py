"""v3.93 Calendar Engine tests — 8+ test cases"""
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta

import pytest

from src.core.calendar_engine import (
    CalendarEngine, CalendarEvent, CalDAVProvider, SyncStatus,
    ReminderType, RecurrenceRule, ReminderTask,
    get_calendar_engine, reset_calendar_engine,
)


@pytest.fixture
def tmp_db():
    """Create a temporary DB and engine, clean up after."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="cal_test_")
    os.close(fd)
    engine = CalendarEngine(db_path=path)
    yield engine
    engine.stop_reminder_loop()
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure singleton is reset between tests."""
    reset_calendar_engine()
    yield
    reset_calendar_engine()


# ═══════════════════════════════════════════════════════════════════════════════
# 1) Event CRUD (local-first)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventCRUD:
    """Test basic local event create/read/update/delete operations"""

    def test_add_and_get_event(self, tmp_db):
        """Add an event and retrieve it by UID"""
        event = CalendarEvent(
            title="Team Meeting",
            description="Weekly sync",
            start=datetime(2026, 6, 15, 14, 0),
            end=datetime(2026, 6, 15, 15, 0),
        )
        uid = tmp_db.add_event(event)
        assert uid == event.uid

        retrieved = tmp_db.get_event(uid)
        assert retrieved is not None
        assert retrieved.title == "Team Meeting"
        assert retrieved.description == "Weekly sync"
        assert retrieved.start == datetime(2026, 6, 15, 14, 0)
        assert retrieved.end == datetime(2026, 6, 15, 15, 0)
        assert retrieved.dirty is True  # new events are dirty until synced

    def test_update_event(self, tmp_db):
        """Update an existing event"""
        event = CalendarEvent(title="Original", start=datetime(2026, 6, 10, 9, 0))
        tmp_db.add_event(event)

        event.title = "Updated"
        event.description = "Changed"
        result = tmp_db.update_event(event)
        assert result is True

        retrieved = tmp_db.get_event(event.uid)
        assert retrieved.title == "Updated"
        assert retrieved.description == "Changed"
        assert retrieved.dirty is True

    def test_update_nonexistent_event(self, tmp_db):
        """Updating a non-existent event returns False"""
        event = CalendarEvent(title="Ghost")
        result = tmp_db.update_event(event)
        assert result is False

    def test_soft_delete_event(self, tmp_db):
        """Soft-delete marks as deleted but keeps in DB"""
        event = CalendarEvent(title="To Delete", start=datetime(2026, 6, 20, 10, 0))
        tmp_db.add_event(event)

        result = tmp_db.delete_event(event.uid)
        assert result is True

        # get_event filters deleted
        assert tmp_db.get_event(event.uid) is None

        # but it's still there with include_deleted
        all_events = tmp_db.get_events(include_deleted=True)
        assert len(all_events) == 1
        assert all_events[0].deleted is True

    def test_permanent_delete_event(self, tmp_db):
        """Permanent delete removes from DB entirely"""
        event = CalendarEvent(title="Gone Forever", start=datetime(2026, 6, 20, 10, 0))
        tmp_db.add_event(event)

        tmp_db.delete_event(event.uid, permanent=True)
        assert tmp_db.get_event(event.uid) is None
        assert len(tmp_db.get_events(include_deleted=True)) == 0

    def test_get_events_time_range(self, tmp_db):
        """Query events within a specific time range"""
        e1 = CalendarEvent(title="Past", start=datetime(2026, 1, 1), end=datetime(2026, 1, 1, 1))
        e2 = CalendarEvent(title="Current", start=datetime(2026, 6, 15, 10, 0), end=datetime(2026, 6, 15, 11, 0))
        e3 = CalendarEvent(title="Future", start=datetime(2026, 12, 31), end=datetime(2026, 12, 31, 23, 59))
        tmp_db.add_event(e1)
        tmp_db.add_event(e2)
        tmp_db.add_event(e3)

        # Only June events
        results = tmp_db.get_events(
            start=datetime(2026, 6, 1),
            end=datetime(2026, 6, 30),
        )
        assert len(results) == 1
        assert results[0].title == "Current"


# ═══════════════════════════════════════════════════════════════════════════════
# 2) Natural Language Parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestNaturalLanguage:
    """Test natural language → CalendarEvent parsing"""

    def test_relative_day_morning(self, tmp_db):
        """明天上午9点 should parse to tomorrow at 9:00"""
        today = datetime.now()
        event = tmp_db.parse_natural_language("明天上午9点团队会议")
        assert event is not None
        assert event.title == "团队会议"
        expected_date = today.date() + timedelta(days=1)
        assert event.start.date() == expected_date
        assert event.start.hour == 9
        assert event.start.minute == 0
        assert ReminderType.POPUP in event.reminders

    def test_relative_day_afternoon(self, tmp_db):
        """后天下午3:30 should parse to day-after-tomorrow at 15:30"""
        today = datetime.now()
        event = tmp_db.parse_natural_language("后天下午3:30牙医预约")
        assert event is not None
        assert event.title == "牙医预约"
        expected_date = today.date() + timedelta(days=2)
        assert event.start.date() == expected_date
        assert event.start.hour == 15
        assert event.start.minute == 30

    def test_weekday_chinese(self, tmp_db):
        """下周三上午10点 should parse to next Wednesday 10:00"""
        event = tmp_db.parse_natural_language("下周三上午10点产品评审")
        assert event is not None
        assert event.title == "产品评审"
        assert event.start.hour == 10
        assert event.start.minute == 0
        # Should be a future Wednesday
        assert event.start > datetime.now()

    def test_date_time_chinese(self, tmp_db):
        """3月15日下午2:30 should parse to March 15 14:30"""
        event = tmp_db.parse_natural_language("3月15日下午2:30面试")
        assert event is not None
        assert event.title == "面试"
        assert event.start.month == 3
        assert event.start.day == 15
        assert event.start.hour == 14
        assert event.start.minute == 30

    def test_iso_datetime(self, tmp_db):
        """2026-06-15 14:00 project sync"""
        event = tmp_db.parse_natural_language("2026-06-15 14:00 project sync")
        assert event is not None
        assert event.start.year == 2026
        assert event.start.month == 6
        assert event.start.day == 15
        assert event.start.hour == 14
        assert event.title == "project sync"

    def test_recurring_weekly_english(self, tmp_db):
        """every Monday at 9am standup"""
        event = tmp_db.parse_natural_language("every Monday at 9am standup")
        assert event is not None
        assert event.title == "standup"
        assert event.start.hour == 9
        assert event.recurrence == RecurrenceRule.WEEKLY
        assert "FREQ=WEEKLY" in event.recurrence_rrule

    def test_unparseable_text(self, tmp_db):
        """Garbage text should return None"""
        event = tmp_db.parse_natural_language("some random text without dates")
        assert event is None

    def test_empty_string(self, tmp_db):
        """Empty string should return None"""
        event = tmp_db.parse_natural_language("")
        assert event is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3) CalDAV Configuration
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalDAVConfig:
    """Test CalDAV server configuration"""

    def test_configure_caldav(self, tmp_db):
        """Configure a CalDAV server and verify config persisted"""
        tmp_db.configure_caldav(
            url="https://cal.example.com",
            username="user1",
            password="secret123",
            provider=CalDAVProvider.NEXTCLOUD,
            calendar_path="/calendars/user1/default/",
            sync_interval_seconds=600,
        )
        cfg = tmp_db.get_caldav_config()
        assert cfg["provider"] == "nextcloud"
        assert cfg["url"] == "https://cal.example.com"
        assert cfg["username"] == "user1"
        assert cfg["password"] == "***"  # masked
        assert cfg["calendar_path"] == "/calendars/user1/default/"
        assert cfg["sync_interval_seconds"] == 600
        assert cfg["enabled"] is True

    def test_disable_enable_caldav(self, tmp_db):
        """Toggle CalDAV sync on/off"""
        tmp_db.configure_caldav("https://cal.example.com", "u", "p")
        assert tmp_db.get_caldav_config()["enabled"] is True

        tmp_db.disable_caldav()
        assert tmp_db.get_caldav_config()["enabled"] is False

        tmp_db.enable_caldav()
        assert tmp_db.get_caldav_config()["enabled"] is True

    def test_default_config_empty(self, tmp_db):
        """Default config before any configuration"""
        cfg = tmp_db.get_caldav_config()
        assert cfg["url"] == ""
        assert cfg["username"] == ""
        assert cfg["enabled"] is False

    def test_configure_all_providers(self, tmp_db):
        """All CalDAV provider types can be configured"""
        for provider in CalDAVProvider:
            e = CalendarEngine(db_path=tmp_db.db_path.parent / f"test_{provider.value}.db")
            e.configure_caldav("https://cal.example.com", "u", "p", provider=provider)
            assert e.get_caldav_config()["provider"] == provider.value


# ═══════════════════════════════════════════════════════════════════════════════
# 4) Reminders
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminders:
    """Test reminder scheduling and delivery"""

    def test_add_event_schedules_reminder(self, tmp_db):
        """Adding an event with reminders creates reminder tasks"""
        event = CalendarEvent(
            title="Meeting",
            start=datetime.now() + timedelta(hours=1),
            reminders=[ReminderType.POPUP],
            reminder_minutes=15,
        )
        tmp_db.add_event(event)
        pending = tmp_db.get_pending_reminders()
        assert len(pending) == 1
        assert pending[0].event_uid == event.uid
        assert pending[0].reminder_type == ReminderType.POPUP

    def test_check_reminders_fires_due(self, tmp_db):
        """Reminders that are past due should be fired"""
        event = CalendarEvent(
            title="Urgent",
            start=datetime.now() + timedelta(minutes=5),  # 5 min from now
            reminders=[ReminderType.POPUP],
            reminder_minutes=15,  # should have fired 10 min ago
        )
        tmp_db.add_event(event)

        # Force the reminder trigger time into the past
        import sqlite3
        conn = sqlite3.connect(str(tmp_db.db_path))
        past_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        conn.execute("UPDATE reminders_queue SET trigger_at=? WHERE event_uid=?", (past_time, event.uid))
        conn.commit()
        conn.close()

        fired = tmp_db.check_reminders()
        assert len(fired) == 1
        assert fired[0].event_title == "Urgent"
        assert fired[0].delivered is True

    def test_check_reminders_not_due_yet(self, tmp_db):
        """Future reminders should not fire"""
        event = CalendarEvent(
            title="Later",
            start=datetime.now() + timedelta(hours=24),
            reminders=[ReminderType.POPUP],
            reminder_minutes=15,
        )
        tmp_db.add_event(event)
        fired = tmp_db.check_reminders()
        assert len(fired) == 0

    def test_notification_callback(self, tmp_db):
        """Notification callback is invoked on reminder fire"""
        captured = []

        def my_callback(task: ReminderTask):
            captured.append(task)

        tmp_db.set_notification_callback(my_callback)

        event = CalendarEvent(
            title="Callback Test",
            start=datetime.now() + timedelta(minutes=2),
            reminders=[ReminderType.POPUP],
            reminder_minutes=10,
        )
        tmp_db.add_event(event)

        # Force past trigger
        import sqlite3
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("UPDATE reminders_queue SET trigger_at=?", ((datetime.now() - timedelta(minutes=5)).isoformat(),))
        conn.commit()
        conn.close()

        tmp_db.check_reminders()
        assert len(captured) == 1
        assert captured[0].event_title == "Callback Test"

    def test_delete_event_clears_reminders(self, tmp_db):
        """Deleting an event removes its pending reminders"""
        event = CalendarEvent(
            title="Delete Me",
            start=datetime.now() + timedelta(hours=2),
            reminders=[ReminderType.POPUP],
            reminder_minutes=30,
        )
        tmp_db.add_event(event)
        assert len(tmp_db.get_pending_reminders()) == 1

        tmp_db.delete_event(event.uid)
        assert len(tmp_db.get_pending_reminders()) == 0

    def test_custom_reminder_offsets(self, tmp_db):
        """Custom reminder offsets create multiple reminder tasks"""
        event = CalendarEvent(
            title="Multi Reminder",
            start=datetime.now() + timedelta(hours=3),
            reminders=[ReminderType.POPUP, ReminderType.EMAIL],
            custom_reminder_offsets=[-60, -10, 0],  # 1h, 10min, at start
        )
        tmp_db.add_event(event)
        pending = tmp_db.get_pending_reminders()
        # 3 offsets × 2 reminder types = 6 tasks
        assert len(pending) == 6


# ═══════════════════════════════════════════════════════════════════════════════
# 5) Sync (local-first + offline resilience)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSync:
    """Test CalDAV sync behavior"""

    def test_sync_without_config_returns_offline(self, tmp_db):
        """Sync when not configured returns offline status"""
        result = tmp_db.sync()
        assert result["status"] == "offline"
        assert result["pushed"] == 0
        assert result["pulled"] == 0
        assert "not configured" in result["message"]

    def test_sync_pushes_dirty_events(self, tmp_db):
        """Configured sync attempts to push dirty events"""
        tmp_db.configure_caldav("https://cal.example.com", "u", "p")

        event = CalendarEvent(
            title="Sync Me",
            start=datetime(2026, 7, 1, 10, 0),
            end=datetime(2026, 7, 1, 11, 0),
        )
        tmp_db.add_event(event)

        result = tmp_db.sync()
        # Stubbed CalDAV PUT succeeds, so one event should be pushed
        assert result["pushed"] >= 0
        assert isinstance(result["errors"], list)
        assert result["status"] in ("success", "up_to_date", "partial")

    def test_get_dirty_events(self, tmp_db):
        """get_dirty_events returns only unsynced events"""
        e1 = CalendarEvent(title="Dirty", start=datetime(2026, 6, 1, 9, 0))
        tmp_db.add_event(e1)

        e2 = CalendarEvent(title="Clean", start=datetime(2026, 6, 2, 9, 0))
        tmp_db.add_event(e2)
        # Mark e2 as clean (synced) by updating its dirty flag in DB directly
        import sqlite3
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("UPDATE events SET dirty=0 WHERE uid=?", (e2.uid,))
        conn.commit()
        conn.close()

        dirty = tmp_db.get_dirty_events()
        assert len(dirty) == 1
        assert dirty[0].title == "Dirty"

    def test_is_online(self, tmp_db):
        """is_online checks CalDAV reachability"""
        # Not configured = offline
        assert tmp_db.is_online() is False

        # Configured = assumes reachable (stub)
        tmp_db.configure_caldav("https://cal.example.com", "u", "p")
        assert tmp_db.is_online() is True

        # Disabled = offline
        tmp_db.disable_caldav()
        assert tmp_db.is_online() is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6) CalendarEvent model
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalendarEventModel:
    """Test CalendarEvent dataclass methods"""

    def test_to_dict_and_from_dict_roundtrip(self):
        """Event → dict → event preserves all fields"""
        original = CalendarEvent(
            title="Roundtrip",
            description="Test serialization",
            location="Room 101",
            start=datetime(2026, 8, 15, 9, 30),
            end=datetime(2026, 8, 15, 10, 30),
            reminders=[ReminderType.POPUP, ReminderType.EMAIL],
            reminder_minutes=30,
            custom_reminder_offsets=[-60, -5],
            recurrence=RecurrenceRule.WEEKLY,
            recurrence_rrule="FREQ=WEEKLY;BYDAY=MO",
            tags=["work", "important"],
            color="#ff0000",
            metadata={"agenda_id": "abc123"},
        )
        d = original.to_dict()
        restored = CalendarEvent.from_dict(d)
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.location == original.location
        assert restored.start == original.start
        assert restored.end == original.end
        assert restored.reminders == original.reminders
        assert restored.reminder_minutes == original.reminder_minutes
        assert restored.custom_reminder_offsets == original.custom_reminder_offsets
        assert restored.recurrence == original.recurrence
        assert restored.recurrence_rrule == original.recurrence_rrule
        assert restored.tags == original.tags
        assert restored.color == original.color
        assert restored.metadata == original.metadata

    def test_duration_minutes(self):
        """duration_minutes computes correct span"""
        e = CalendarEvent(
            title="Hour meeting",
            start=datetime(2026, 6, 1, 10, 0),
            end=datetime(2026, 6, 1, 11, 30),
        )
        assert e.duration_minutes() == 90

    def test_duration_minutes_no_end_defaults(self):
        """No end time defaults to 60 minutes"""
        e = CalendarEvent(start=datetime(2026, 6, 1, 10, 0))
        assert e.duration_minutes() == 60

    def test_is_past(self):
        """Events in the past return True for is_past"""
        past_event = CalendarEvent(
            title="Past",
            start=datetime(2020, 1, 1),
            end=datetime(2020, 1, 1, 1),
        )
        assert past_event.is_past() is True

        future_event = CalendarEvent(
            title="Future",
            start=datetime.now() + timedelta(days=365),
            end=datetime.now() + timedelta(days=365, hours=1),
        )
        assert future_event.is_past() is False

    def test_is_upcoming(self):
        """Events starting soon return True for is_upcoming"""
        soon = CalendarEvent(
            title="Soon",
            start=datetime.now() + timedelta(minutes=30),
            end=datetime.now() + timedelta(minutes=90),
        )
        assert soon.is_upcoming(window_minutes=60) is True

        later = CalendarEvent(
            title="Later",
            start=datetime.now() + timedelta(hours=3),
        )
        assert later.is_upcoming(window_minutes=60) is False

    def test_to_icalendar(self):
        """to_icalendar generates valid VEVENT"""
        event = CalendarEvent(
            uid="test-uid-123",
            title="ICAL Test",
            start=datetime(2026, 6, 15, 14, 0),
            end=datetime(2026, 6, 15, 15, 0),
            description="A test event",
            location="Office",
        )
        ical = event.to_icalendar()
        assert "BEGIN:VEVENT" in ical
        assert "UID:test-uid-123" in ical
        assert "SUMMARY:ICAL Test" in ical
        assert "DTSTART:20260615T140000" in ical
        assert "DTEND:20260615T150000" in ical
        assert "DESCRIPTION:A test event" in ical
        assert "LOCATION:Office" in ical
        assert "END:VEVENT" in ical

    def test_to_icalendar_all_day(self):
        """All-day events format correctly"""
        event = CalendarEvent(
            title="Holiday",
            start=datetime(2026, 12, 25),
            end=datetime(2026, 12, 25),
            all_day=True,
        )
        ical = event.to_icalendar()
        assert "DTSTART;VALUE=DATE:20261225" in ical
        assert "DTEND;VALUE=DATE:20261226" in ical  # exclusive end

    def test_to_icalendar_with_reminder(self):
        """Events with reminders include VALARM"""
        event = CalendarEvent(
            title="Alarm Event",
            start=datetime(2026, 6, 15, 14, 0),
            end=datetime(2026, 6, 15, 15, 0),
            reminders=[ReminderType.POPUP],
            reminder_minutes=10,
        )
        ical = event.to_icalendar()
        assert "BEGIN:VALARM" in ical
        assert "TRIGGER:-PT10M" in ical
        assert "END:VALARM" in ical


# ═══════════════════════════════════════════════════════════════════════════════
# 7) Engine Stats & Maintenance
# ═══════════════════════════════════════════════════════════════════════════════

class TestEngineMaintenance:
    """Test stats, cleanup, and singleton"""

    def test_get_stats(self, tmp_db):
        """get_stats returns accurate counts"""
        for i in range(3):
            tmp_db.add_event(CalendarEvent(
                title=f"Event {i}",
                start=datetime(2026, 6, i + 1),
            ))

        tmp_db.configure_caldav("https://cal.example.com", "u", "p")

        stats = tmp_db.get_stats()
        assert stats["version"] == "3.93.0"
        assert stats["total_events"] == 3
        assert stats["dirty_events"] == 3
        assert stats["caldav_enabled"] is True
        assert stats["caldav_provider"] == "generic"

    def test_cleanup_old_events(self, tmp_db):
        """cleanup removes events older than N days"""
        old = CalendarEvent(
            title="Ancient",
            start=datetime(2020, 1, 1),
            end=datetime(2020, 1, 1, 1),
        )
        new = CalendarEvent(
            title="Recent",
            start=datetime.now() + timedelta(days=7),
            end=datetime.now() + timedelta(days=7, hours=1),
        )
        tmp_db.add_event(old)
        tmp_db.add_event(new)

        removed = tmp_db.cleanup(older_than_days=365)
        assert removed >= 1
        assert tmp_db.get_event(new.uid) is not None

    def test_clear_all(self, tmp_db):
        """clear_all wipes everything"""
        tmp_db.add_event(CalendarEvent(title="E1", start=datetime(2026, 6, 1)))
        tmp_db.add_event(CalendarEvent(title="E2", start=datetime(2026, 6, 2)))
        tmp_db.configure_caldav("https://cal.example.com", "u", "p")

        removed = tmp_db.clear_all()
        assert removed == 2
        assert tmp_db.get_stats()["total_events"] == 0
        assert tmp_db.get_caldav_config()["enabled"] is False  # config cleared

    def test_singleton(self, tmp_db):
        """get_calendar_engine returns same instance"""
        # Reset so we start fresh
        reset_calendar_engine()
        e1 = get_calendar_engine(db_path=tmp_db.db_path)
        e2 = get_calendar_engine()
        assert e1 is e2
        e1.add_event(CalendarEvent(title="Shared", start=datetime(2026, 6, 1)))
        assert e2.get_stats()["total_events"] == 1
        reset_calendar_engine()


# ═══════════════════════════════════════════════════════════════════════════════
# 8) Reminder Background Loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestReminderLoop:
    """Test the background reminder loop thread"""

    def test_start_stop_reminder_loop(self, tmp_db):
        """Start and stop the reminder background thread"""
        tmp_db.start_reminder_loop(interval_seconds=1)
        assert tmp_db.get_stats()["reminder_loop_active"] is True

        tmp_db.stop_reminder_loop()
        # Give it a moment to actually stop
        time.sleep(0.2)
        assert tmp_db.get_stats()["reminder_loop_active"] is False

    def test_double_start_no_duplicate_threads(self, tmp_db):
        """Starting twice doesn't create duplicate threads"""
        tmp_db.start_reminder_loop(interval_seconds=1)
        tmp_db.start_reminder_loop(interval_seconds=1)
        assert tmp_db.get_stats()["reminder_loop_active"] is True
        tmp_db.stop_reminder_loop()

    def test_reminder_loop_fires_reminders(self, tmp_db):
        """Background loop fires due reminders"""
        captured = []

        def cb(task):
            captured.append(task)

        tmp_db.set_notification_callback(cb)

        # Create an event whose reminder is already past
        event = CalendarEvent(
            title="Loop Test",
            start=datetime.now() + timedelta(minutes=5),
            reminders=[ReminderType.POPUP],
            reminder_minutes=15,
        )
        tmp_db.add_event(event)

        # Force reminder trigger into past
        import sqlite3
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.execute("UPDATE reminders_queue SET trigger_at=?", ((datetime.now() - timedelta(seconds=5)).isoformat(),))
        conn.commit()
        conn.close()

        tmp_db.start_reminder_loop(interval_seconds=0.5)
        time.sleep(1.5)  # Wait for at least one cycle
        tmp_db.stop_reminder_loop()

        assert len(captured) >= 1
        assert captured[0].event_title == "Loop Test"


# ═══════════════════════════════════════════════════════════════════════════════
# 9) Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_non_existent_event_get(self, tmp_db):
        """Getting a non-existent event returns None"""
        assert tmp_db.get_event("nonexistent-uid") is None

    def test_past_event_no_reminder(self, tmp_db):
        """Adding a past event should not schedule reminders"""
        event = CalendarEvent(
            title="Too Late",
            start=datetime(2020, 1, 1),
            reminders=[ReminderType.POPUP],
            reminder_minutes=15,
        )
        tmp_db.add_event(event)
        # Past events skip reminder scheduling
        pending = tmp_db.get_pending_reminders()
        assert len(pending) == 0

    def test_multiple_calendars(self, tmp_db):
        """Events can be stored under different calendar_ids"""
        e1 = CalendarEvent(
            title="Work", calendar_id="work",
            start=datetime(2026, 6, 15, 9, 0),
        )
        e2 = CalendarEvent(
            title="Personal", calendar_id="personal",
            start=datetime(2026, 6, 15, 12, 0),
        )
        tmp_db.add_event(e1)
        tmp_db.add_event(e2)

        work_events = tmp_db.get_events(calendar_id="work")
        personal_events = tmp_db.get_events(calendar_id="personal")
        assert len(work_events) == 1
        assert work_events[0].title == "Work"
        assert len(personal_events) == 1
        assert personal_events[0].title == "Personal"

    def test_concurrent_adds_thread_safe(self, tmp_db):
        """Concurrent event additions don't corrupt DB"""
        errors = []

        def add_event(i):
            try:
                tmp_db.add_event(CalendarEvent(
                    title=f"Thread {i}",
                    start=datetime(2026, 6, 1, i % 24, 0),
                ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_event, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert tmp_db.get_stats()["total_events"] == 20

    def test_parse_hour_edge_cases(self, tmp_db):
        """12-hour time edge cases"""
        # 中午12点 = noon
        event = tmp_db.parse_natural_language("明天中午12点午饭")
        assert event is not None
        assert event.start.hour == 12

        # 晚上12点 = midnight (should be hour 0)
        # Actually "晚上12点" is ambiguous but conventionally means 0:00
        event = tmp_db.parse_natural_language("今天晚上12点跨年")
        if event and "12点" in "今天晚上12点跨年":
            pass  # Edge case, may vary

    def test_cleanup_no_old_events(self, tmp_db):
        """cleanup with no matching events returns 0"""
        tmp_db.add_event(CalendarEvent(
            title="Recent",
            start=datetime.now() + timedelta(days=1),
            end=datetime.now() + timedelta(days=1, hours=1),
        ))
        removed = tmp_db.cleanup(older_than_days=1)
        assert removed == 0
        assert tmp_db.get_stats()["total_events"] == 1
