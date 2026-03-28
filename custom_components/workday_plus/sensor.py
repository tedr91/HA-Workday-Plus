"""Sensor entities for Workday Plus."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from holidays import HolidayBase

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import WorkdayConfigEntry
from .const import (
    CONF_EXCLUDES,
    CONF_EXCLUSION_CALENDARS,
    CONF_EXCLUSION_CALENDAR_RULES,
    CONF_OFFSET,
    CONF_REFRESH_INTERVAL_MINUTES,
    CONF_WORKDAYS,
    DEFAULT_EXCLUDES,
    DEFAULT_EXCLUSION_CALENDAR_RULES,
    DEFAULT_NAME,
    DEFAULT_OFFSET,
    DEFAULT_REFRESH_INTERVAL_MINUTES,
    DEFAULT_WORKDAYS,
)
from .entity import BaseWorkdayEntity

WORKDAY_ALARM_TIME_SUFFIX = "workday_alarm_time"
OFFDAY_ALARM_TIME_SUFFIX = "offday_alarm_time"
WORKDAY_ALARM_ENABLED_SUFFIX = "workday_alarm_enabled"
OFFDAY_ALARM_ENABLED_SUFFIX = "offday_alarm_enabled"


async def async_setup_entry(
    hass,
    entry: WorkdayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Workday Plus sensors."""
    options = entry.options
    days_offset: int = int(options.get(CONF_OFFSET, DEFAULT_OFFSET))
    refresh_interval_minutes: int = int(
        options.get(CONF_REFRESH_INTERVAL_MINUTES, DEFAULT_REFRESH_INTERVAL_MINUTES)
    )
    excludes: list[str] = options.get(CONF_EXCLUDES, DEFAULT_EXCLUDES)
    exclusion_calendars: list[str] = options.get(CONF_EXCLUSION_CALENDARS, [])
    exclusion_calendar_rules: dict[str, dict[str, bool | list[str]]] = options.get(
        CONF_EXCLUSION_CALENDAR_RULES,
        DEFAULT_EXCLUSION_CALENDAR_RULES,
    )
    sensor_name: str = options.get(CONF_NAME, DEFAULT_NAME)
    workdays: list[str] = options.get(CONF_WORKDAYS, DEFAULT_WORKDAYS)
    obj_holidays = entry.runtime_data

    async_add_entities(
        [
            NextActiveAlarmSensor(
                obj_holidays,
                workdays,
                excludes,
                exclusion_calendars,
                exclusion_calendar_rules,
                days_offset,
                refresh_interval_minutes,
                sensor_name,
                entry.entry_id,
            )
        ],
    )


class NextActiveAlarmSensor(BaseWorkdayEntity, SensorEntity):
    """Representation of next active alarm date-time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_translation_key = "next_active_alarm"

    def __init__(
        self,
        obj_holidays: HolidayBase,
        workdays: list[str],
        excludes: list[str],
        exclusion_calendars: list[str],
        exclusion_calendar_rules: dict[str, dict[str, bool | list[str]]],
        days_offset: int,
        refresh_interval_minutes: int,
        name: str,
        entry_id: str,
    ) -> None:
        """Initialize next active alarm sensor."""
        super().__init__(
            obj_holidays,
            workdays,
            excludes,
            exclusion_calendars,
            exclusion_calendar_rules,
            days_offset,
            refresh_interval_minutes,
            name,
            entry_id,
        )
        self._entry_id = entry_id
        self._attr_native_value: datetime | None = None
        self._entity_ids: dict[str, str] = {}
        self._attr_extra_state_attributes = {
            "next_alarm_type": None,
            "workday_alarm_time": None,
            "offday_alarm_time": None,
            "workday_alarm_enabled": None,
            "offday_alarm_enabled": None,
        }

    def update_data(self, now: datetime) -> None:
        """Update data for next active alarm."""
        self._refresh_entity_ids()

        workday_alarm_time = self._read_alarm_time(WORKDAY_ALARM_TIME_SUFFIX)
        offday_alarm_time = self._read_alarm_time(OFFDAY_ALARM_TIME_SUFFIX)
        workday_alarm_enabled = self._read_alarm_enabled(WORKDAY_ALARM_ENABLED_SUFFIX)
        offday_alarm_enabled = self._read_alarm_enabled(OFFDAY_ALARM_ENABLED_SUFFIX)

        next_alarm = self._calculate_next_alarm(
            now=now,
            workday_alarm_time=workday_alarm_time,
            offday_alarm_time=offday_alarm_time,
            workday_alarm_enabled=workday_alarm_enabled,
            offday_alarm_enabled=offday_alarm_enabled,
        )

        self._attr_native_value = next_alarm[0]
        self._attr_extra_state_attributes = {
            "next_alarm_type": next_alarm[1],
            "workday_alarm_time": str(workday_alarm_time) if workday_alarm_time else None,
            "offday_alarm_time": str(offday_alarm_time) if offday_alarm_time else None,
            "workday_alarm_enabled": workday_alarm_enabled,
            "offday_alarm_enabled": offday_alarm_enabled,
        }

    def _refresh_entity_ids(self) -> None:
        """Refresh local cache of platform entity ids."""
        entity_registry = er.async_get(self.hass)
        for entry in er.async_entries_for_config_entry(entity_registry, self._entry_id):
            unique_id = entry.unique_id
            if unique_id.endswith(WORKDAY_ALARM_TIME_SUFFIX):
                self._entity_ids[WORKDAY_ALARM_TIME_SUFFIX] = entry.entity_id
            elif unique_id.endswith(OFFDAY_ALARM_TIME_SUFFIX):
                self._entity_ids[OFFDAY_ALARM_TIME_SUFFIX] = entry.entity_id
            elif unique_id.endswith(WORKDAY_ALARM_ENABLED_SUFFIX):
                self._entity_ids[WORKDAY_ALARM_ENABLED_SUFFIX] = entry.entity_id
            elif unique_id.endswith(OFFDAY_ALARM_ENABLED_SUFFIX):
                self._entity_ids[OFFDAY_ALARM_ENABLED_SUFFIX] = entry.entity_id

    def _read_alarm_time(self, suffix: str):
        """Read a configured alarm time from state."""
        entity_id = self._entity_ids.get(suffix)
        if entity_id is None:
            return None

        state = self.hass.states.get(entity_id)
        if state is None:
            return None

        return dt_util.parse_time(state.state)

    def _read_alarm_enabled(self, suffix: str) -> bool | None:
        """Read alarm enabled state from switch."""
        entity_id = self._entity_ids.get(suffix)
        if entity_id is None:
            return None

        state = self.hass.states.get(entity_id)
        if state is None:
            return None

        return state.state == "on"

    def _calculate_next_alarm(
        self,
        now: datetime,
        workday_alarm_time,
        offday_alarm_time,
        workday_alarm_enabled: bool | None,
        offday_alarm_enabled: bool | None,
    ) -> tuple[datetime | None, str | None]:
        """Find next alarm datetime in UTC and alarm type."""
        if workday_alarm_time is None and offday_alarm_time is None:
            return (None, None)

        local_now = dt_util.as_local(now)

        for day_delta in range(0, 30):
            candidate_date = local_now.date() + timedelta(days=day_delta)
            is_workday = self.date_is_workday(candidate_date)

            if is_workday:
                if not workday_alarm_enabled or workday_alarm_time is None:
                    continue
                candidate_local = self._build_local_datetime(
                    candidate_date,
                    workday_alarm_time,
                    local_now,
                )
                if candidate_local > local_now:
                    return (dt_util.as_utc(candidate_local), "workday")
            else:
                if not offday_alarm_enabled or offday_alarm_time is None:
                    continue
                candidate_local = self._build_local_datetime(
                    candidate_date,
                    offday_alarm_time,
                    local_now,
                )
                if candidate_local > local_now:
                    return (dt_util.as_utc(candidate_local), "offday")

        return (None, None)

    def _build_local_datetime(self, alarm_date: date, alarm_time, now: datetime) -> datetime:
        """Build timezone-aware local datetime for an alarm."""
        return datetime.combine(alarm_date, alarm_time, tzinfo=now.tzinfo)
