"""Base workday entity."""

from __future__ import annotations

from abc import abstractmethod
from datetime import date, datetime, timedelta
from typing import Any

from holidays import HolidayBase, __version__ as python_holidays_version

from homeassistant.core import CALLBACK_TYPE, ServiceResponse, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import ALLOWED_DAYS, DOMAIN


class BaseWorkdayEntity(Entity):
    """Implementation of a base Workday entity."""

    _attr_has_entity_name = True
    _attr_translation_key = DOMAIN
    _attr_should_poll = False
    unsub: CALLBACK_TYPE | None = None

    def __init__(
        self,
        obj_holidays: HolidayBase,
        workdays: list[str],
        excludes: list[str],
        exclusion_calendars: list[str],
        days_offset: int,
        name: str,
        entry_id: str,
    ) -> None:
        """Initialize the Workday entity."""
        self._obj_holidays = obj_holidays
        self._workdays = workdays
        self._excludes = excludes
        self._exclusion_calendars = exclusion_calendars
        self._days_offset = days_offset
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
        self.unsub = async_track_point_in_utc_time(
            self.hass, self.point_in_time_listener, self.get_next_interval(now)
        )

    @callback
    def point_in_time_listener(self, time_date: datetime) -> None:
        """Get the latest data and update state."""
        self.hass.async_create_task(self._async_refresh_and_write_state())

    async def async_added_to_hass(self) -> None:
        """Set up first update."""
        await self._async_update_exclusion_dates()
        self._update_state_and_setup_listener()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up listeners on removal."""
        if self.unsub is not None:
            self.unsub()
            self.unsub = None

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
                    excluded_dates.update(self._extract_all_day_event_dates(event))

        self._calendar_excluded_dates = excluded_dates

    def _extract_all_day_event_dates(self, event: Any) -> set[date]:
        """Return all covered dates for all-day events."""
        if not isinstance(event, dict):
            return set()

        is_all_day = event.get("all_day")
        start_date = self._coerce_date(event.get("start"))
        end_date = self._coerce_date(event.get("end"))

        if start_date is None:
            return set()

        if is_all_day is False:
            return set()

        if isinstance(event.get("start"), str) and "T" in event["start"] and not is_all_day:
            return set()

        if end_date is None:
            return {start_date}

        last_date = end_date - timedelta(days=1)
        if last_date < start_date:
            return {start_date}

        return {
            start_date + timedelta(days=offset)
            for offset in range((last_date - start_date).days + 1)
        }

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
