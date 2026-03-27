"""Base workday entity."""

from __future__ import annotations

from abc import abstractmethod
from datetime import date, datetime, time, timedelta
from typing import Any

from holidays import HolidayBase, __version__ as python_holidays_version

from homeassistant.core import CALLBACK_TYPE, ServiceResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import ALLOWED_DAYS, DOMAIN, LOGGER

EventWordRule = tuple[str, time, time]


class BaseWorkdayEntity(Entity):
    """Implementation of a base Workday entity."""

    _attr_has_entity_name = True
    _attr_translation_key = DOMAIN
    _attr_should_poll = False
    _midnight_unsub: CALLBACK_TYPE | None = None
    _interval_unsub: CALLBACK_TYPE | None = None
    _calendar_change_unsub: CALLBACK_TYPE | None = None

    def __init__(
        self,
        obj_holidays: HolidayBase,
        workdays: list[str],
        excludes: list[str],
        exclusion_calendars: list[str],
        trigger_on_any_all_day_events: bool,
        trigger_on_event_words: list[str],
        days_offset: int,
        refresh_interval_minutes: int,
        name: str,
        entry_id: str,
    ) -> None:
        """Initialize the Workday entity."""
        self._obj_holidays = obj_holidays
        self._workdays = workdays
        self._excludes = excludes
        self._exclusion_calendars = exclusion_calendars
        self._trigger_on_any_all_day_events = trigger_on_any_all_day_events
        self._trigger_on_event_words = self._parse_event_word_rules(
            trigger_on_event_words
        )
        self._days_offset = days_offset
        self._refresh_interval = timedelta(minutes=refresh_interval_minutes)
        self._calendar_excluded_dates: set[date] = set()
        self._attr_unique_id = entry_id
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="python-holidays",
            model=python_holidays_version,
            name=name,
        )

    def is_include(self, day: str, now: date) -> bool:
        """Check if given day is in the includes list."""
        if day in self._workdays:
            return True
        if "holiday" in self._workdays and now in self._obj_holidays:
            return True

        return False

    def is_exclude(self, day: str, now: date) -> bool:
        """Check if given day is in the excludes list."""
        if day in self._excludes:
            return True
        if "holiday" in self._excludes and now in self._obj_holidays:
            return True

        return False

    def get_next_interval(self, now: datetime) -> datetime:
        """Compute next time an update should occur."""
        tomorrow = dt_util.as_local(now) + timedelta(days=1)
        return dt_util.start_of_local_day(tomorrow)

    def _update_state_and_setup_listener(self) -> None:
        """Update state and setup listener for next interval."""
        now = dt_util.now()
        self.update_data(now)
        if self._midnight_unsub is not None:
            self._midnight_unsub()
            self._midnight_unsub = None
        self._midnight_unsub = async_track_point_in_utc_time(
            self.hass, self.point_in_time_listener, self.get_next_interval(now)
        )

    def _setup_interval_listener(self) -> None:
        """Set up refresh interval listener."""
        if self._interval_unsub is not None:
            self._interval_unsub()
            self._interval_unsub = None
        self._interval_unsub = async_track_time_interval(
            self.hass, self.interval_listener, self._refresh_interval
        )

    def _setup_calendar_change_listener(self) -> None:
        """Set up refresh listener for exclusion calendar state changes."""
        if self._calendar_change_unsub is not None:
            self._calendar_change_unsub()
            self._calendar_change_unsub = None
        if not self._exclusion_calendars:
            return
        self._calendar_change_unsub = async_track_state_change_event(
            self.hass, self._exclusion_calendars, self.calendar_change_listener
        )

    @callback
    def point_in_time_listener(self, time_date: datetime) -> None:
        """Get the latest data and update state."""
        self.hass.async_create_task(self._async_refresh_and_write_state())

    @callback
    def interval_listener(self, time_date: datetime) -> None:
        """Refresh entity state on time interval."""
        self.hass.async_create_task(self._async_refresh_and_write_state())

    @callback
    def calendar_change_listener(self, event: Any) -> None:
        """Refresh entity state when exclusion calendars change."""
        self.hass.async_create_task(self._async_refresh_and_write_state())

    async def async_added_to_hass(self) -> None:
        """Set up first update."""
        await self._async_update_exclusion_dates()
        self._update_state_and_setup_listener()
        self._setup_interval_listener()
        self._setup_calendar_change_listener()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up listeners on removal."""
        if self._midnight_unsub is not None:
            self._midnight_unsub()
            self._midnight_unsub = None
        if self._interval_unsub is not None:
            self._interval_unsub()
            self._interval_unsub = None
        if self._calendar_change_unsub is not None:
            self._calendar_change_unsub()
            self._calendar_change_unsub = None

    async def _async_refresh_and_write_state(self) -> None:
        """Refresh exclusion dates and update state."""
        await self._async_update_exclusion_dates()
        self._update_state_and_setup_listener()
        self.async_write_ha_state()

    async def _async_update_exclusion_dates(self) -> None:
        """Load all-day exclusion dates from selected calendar entities."""
        if not self._exclusion_calendars:
            self._calendar_excluded_dates = set()
            return

        now = dt_util.now()
        start_of_year = dt_util.start_of_local_day(datetime(now.year, 1, 1))
        end_of_next_year = dt_util.start_of_local_day(datetime(now.year + 2, 1, 1))

        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": self._exclusion_calendars,
                    "start_date_time": start_of_year.isoformat(),
                    "end_date_time": end_of_next_year.isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, ServiceNotFound) as err:
            LOGGER.warning(
                "Unable to refresh exclusion calendar events for %s: %s",
                self.entity_id,
                err,
            )
            self._calendar_excluded_dates = set()
            return

        excluded_dates: set[date] = set()
        if isinstance(response, dict):
            for value in response.values():
                events: Any = None
                if isinstance(value, dict):
                    events = value.get("events")
                elif isinstance(value, list):
                    events = value
                if not isinstance(events, list):
                    continue
                for event in events:
                    excluded_dates.update(self._extract_excluded_dates(event))

        self._calendar_excluded_dates = excluded_dates

    def _extract_excluded_dates(self, event: Any) -> set[date]:
        """Return excluded dates for an event using configured trigger rules."""
        if not isinstance(event, dict):
            return set()

        event_title = str(event.get("summary") or event.get("title") or "").lower()
        matches_all_day_trigger = (
            self._trigger_on_any_all_day_events and self._is_all_day_event(event)
        )

        excluded_dates: set[date] = set()
        if matches_all_day_trigger:
            excluded_dates.update(
                self._extract_event_dates(event, include_partial_end_day=False)
            )

        excluded_dates.update(self._extract_word_trigger_dates(event, event_title))
        return excluded_dates

    def _extract_word_trigger_dates(
        self, event: dict[str, Any], event_title: str
    ) -> set[date]:
        """Return excluded dates from configured word triggers and time windows."""
        if not self._trigger_on_event_words:
            return set()

        is_all_day = self._is_all_day_event(event)
        candidate_dates = self._extract_event_dates(
            event, include_partial_end_day=not is_all_day
        )
        if not candidate_dates:
            return set()

        excluded_dates: set[date] = set()
        for word, start_time, end_time in self._trigger_on_event_words:
            if word not in event_title:
                continue
            if is_all_day:
                excluded_dates.update(candidate_dates)
                continue

            for candidate_date in candidate_dates:
                if self._event_overlaps_time_range_on_date(
                    event, candidate_date, start_time, end_time
                ):
                    excluded_dates.add(candidate_date)

        return excluded_dates

    def _parse_event_word_rules(
        self, trigger_on_event_words: list[str]
    ) -> list[EventWordRule]:
        """Parse trigger words with optional time ranges."""
        parsed_rules: list[EventWordRule] = []
        for raw_rule in trigger_on_event_words:
            normalized_rule = raw_rule.strip()
            if not normalized_rule:
                continue

            parsed_rule = self._parse_event_word_rule(normalized_rule)
            if parsed_rule is None:
                continue
            parsed_rules.append(parsed_rule)

        return parsed_rules

    def _parse_event_word_rule(self, raw_rule: str) -> EventWordRule | None:
        """Parse one rule in either `word` or `word|HH:MM-HH:MM` format."""
        default_start = time(0, 0)
        default_end = time(23, 59)

        keyword_part = raw_rule
        range_part = ""
        if "|" in raw_rule:
            keyword_part, range_part = raw_rule.split("|", maxsplit=1)

        keyword = keyword_part.strip().lower()
        if not keyword:
            return None

        if not range_part.strip():
            return (keyword, default_start, default_end)

        parsed_range = self._parse_hhmm_range(range_part.strip())
        if parsed_range is None:
            LOGGER.warning(
                "Invalid trigger word time range `%s` for %s; using full-day default",
                raw_rule,
                self.entity_id,
            )
            return (keyword, default_start, default_end)

        return (keyword, parsed_range[0], parsed_range[1])

    def _parse_hhmm_range(self, raw_range: str) -> tuple[time, time] | None:
        """Parse `HH:MM-HH:MM` time range."""
        if "-" not in raw_range:
            return None

        raw_start, raw_end = raw_range.split("-", maxsplit=1)
        start_time = self._parse_hhmm(raw_start.strip())
        end_time = self._parse_hhmm(raw_end.strip())
        if start_time is None or end_time is None:
            return None

        return (start_time, end_time)

    def _parse_hhmm(self, value: str) -> time | None:
        """Parse one `HH:MM` value into a time object."""
        try:
            parsed_time = time.fromisoformat(value)
        except ValueError:
            return None

        if parsed_time.second != 0 or parsed_time.microsecond != 0:
            return None

        return parsed_time

    def _event_overlaps_time_range_on_date(
        self,
        event: dict[str, Any],
        event_date: date,
        start_time: time,
        end_time: time,
    ) -> bool:
        """Return whether an event overlaps a configured time range on a date."""
        event_start = self._coerce_datetime(event.get("start"))
        event_end = self._coerce_datetime(event.get("end"))
        if event_start is None:
            return False

        event_start_local = self._to_local_naive(event_start)
        event_end_local = self._to_local_naive(event_end or event_start)
        if event_end_local < event_start_local:
            event_end_local = event_start_local

        day_start = datetime.combine(event_date, time.min)
        next_day_start = day_start + timedelta(days=1)

        segment_start = max(event_start_local, day_start)
        segment_end = min(event_end_local, next_day_start)
        if segment_end < segment_start:
            return False

        window_segments = self._time_windows_for_day(event_date, start_time, end_time)
        return any(
            segment_start <= window_end and window_start <= segment_end
            for window_start, window_end in window_segments
        )

    def _time_windows_for_day(
        self, event_date: date, start_time: time, end_time: time
    ) -> list[tuple[datetime, datetime]]:
        """Build one or two datetime windows for a daily time range."""
        if start_time <= end_time:
            return [
                (
                    datetime.combine(event_date, start_time),
                    datetime.combine(event_date, end_time),
                )
            ]

        return [
            (
                datetime.combine(event_date, time.min),
                datetime.combine(event_date, end_time),
            ),
            (
                datetime.combine(event_date, start_time),
                datetime.combine(event_date, time.max),
            ),
        ]

    def _to_local_naive(self, value: datetime) -> datetime:
        """Convert a datetime to local naive representation."""
        local_value = dt_util.as_local(value) if value.tzinfo else value
        return local_value.replace(tzinfo=None)

    def _extract_event_dates(self, event: dict[str, Any], include_partial_end_day: bool) -> set[date]:
        """Return all covered dates for an event."""
        is_all_day = event.get("all_day")
        start_date = self._coerce_date(event.get("start"))
        end_date = self._coerce_date(event.get("end"))

        if start_date is None:
            return set()

        if end_date is None:
            return {start_date}

        if include_partial_end_day:
            last_date = end_date
        else:
            last_date = end_date - timedelta(days=1)

        if is_all_day is False and include_partial_end_day and last_date < start_date:
            last_date = start_date

        if last_date < start_date:
            return {start_date}

        return {
            start_date + timedelta(days=offset)
            for offset in range((last_date - start_date).days + 1)
        }

    def _is_all_day_event(self, event: dict[str, Any]) -> bool:
        """Detect whether an event is all-day."""
        if event.get("all_day") is True:
            return True

        start_value = event.get("start")
        end_value = event.get("end")
        return isinstance(start_value, str) and "T" not in start_value and isinstance(
            end_value, str
        ) and "T" not in end_value

    def _coerce_date(self, value: Any) -> date | None:
        """Convert date-like values into date objects."""
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if not isinstance(value, str):
            return None

        parsed_date = dt_util.parse_date(value)
        if parsed_date is not None:
            return parsed_date

        parsed_datetime = dt_util.parse_datetime(value)
        if parsed_datetime is not None:
            return parsed_datetime.date()

        return None

    def _coerce_datetime(self, value: Any) -> datetime | None:
        """Convert datetime-like values into datetime objects."""
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            return None

        parsed_datetime = dt_util.parse_datetime(value)
        if parsed_datetime is not None:
            return parsed_datetime

        parsed_date = dt_util.parse_date(value)
        if parsed_date is None:
            return None

        return datetime.combine(parsed_date, time.min)

    @abstractmethod
    def update_data(self, now: datetime) -> None:
        """Update data."""

    def check_date(self, check_date: date) -> ServiceResponse:
        """Service to check if date is workday or not."""
        return {"workday": self.date_is_workday(check_date)}

    def date_is_workday(self, check_date: date) -> bool:
        """Check if date is workday."""
        # Default is no workday
        is_workday = False

        # Get ISO day of the week (1 = Monday, 7 = Sunday)
        adjusted_date = check_date + timedelta(days=self._days_offset)
        day = adjusted_date.isoweekday() - 1
        day_of_week = ALLOWED_DAYS[day]

        if self.is_include(day_of_week, adjusted_date):
            is_workday = True

        if self.is_exclude(day_of_week, adjusted_date):
            is_workday = False

        if is_workday and adjusted_date in self._calendar_excluded_dates:
            is_workday = False

        return is_workday
