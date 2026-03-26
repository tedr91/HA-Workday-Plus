"""Sensor to indicate whether the current day is a workday."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from holidays import HolidayBase
import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    async_get_current_platform,
)

from . import WorkdayConfigEntry
from .const import (
    CONF_EXCLUDES,
    CONF_EXCLUSION_CALENDARS,
    CONF_OFFSET,
    CONF_REFRESH_INTERVAL_MINUTES,
    CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
    CONF_TRIGGER_ON_EVENT_WORDS,
    CONF_WORKDAYS,
    DEFAULT_EXCLUDES,
    DEFAULT_NAME,
    DEFAULT_OFFSET,
    DEFAULT_REFRESH_INTERVAL_MINUTES,
    DEFAULT_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
    DEFAULT_TRIGGER_ON_EVENT_WORDS,
    DEFAULT_WORKDAYS,
)
from .entity import BaseWorkdayEntity

SERVICE_CHECK_DATE: Final = "check_date"
CHECK_DATE: Final = "check_date"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WorkdayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Workday sensor."""
    options = entry.options
    days_offset: int = int(options.get(CONF_OFFSET, DEFAULT_OFFSET))
    refresh_interval_minutes: int = int(
        options.get(CONF_REFRESH_INTERVAL_MINUTES, DEFAULT_REFRESH_INTERVAL_MINUTES)
    )
    excludes: list[str] = options.get(CONF_EXCLUDES, DEFAULT_EXCLUDES)
    exclusion_calendars: list[str] = options.get(CONF_EXCLUSION_CALENDARS, [])
    trigger_on_any_all_day_events: bool = entry.options.get(
        CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
        DEFAULT_TRIGGER_ON_ANY_ALL_DAY_EVENTS,
    )
    trigger_on_event_words: list[str] = options.get(
        CONF_TRIGGER_ON_EVENT_WORDS, DEFAULT_TRIGGER_ON_EVENT_WORDS
    )
    sensor_name: str = options.get(CONF_NAME, DEFAULT_NAME)
    workdays: list[str] = options.get(CONF_WORKDAYS, DEFAULT_WORKDAYS)
    obj_holidays = entry.runtime_data

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_CHECK_DATE,
        {vol.Required(CHECK_DATE): cv.date},
        "check_date",
        None,
        SupportsResponse.ONLY,
    )

    async_add_entities(
        [
            IsWorkdaySensor(
                obj_holidays,
                workdays,
                excludes,
                exclusion_calendars,
                trigger_on_any_all_day_events,
                trigger_on_event_words,
                days_offset,
                refresh_interval_minutes,
                sensor_name,
                entry.entry_id,
            )
        ],
    )


class IsWorkdaySensor(BaseWorkdayEntity, BinarySensorEntity):
    """Implementation of a Workday sensor."""

    _attr_name = None

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
        """Initialize the Workday sensor."""
        super().__init__(
            obj_holidays,
            workdays,
            excludes,
            exclusion_calendars,
            trigger_on_any_all_day_events,
            trigger_on_event_words,
            days_offset,
            refresh_interval_minutes,
            name,
            entry_id,
        )
        self._attr_extra_state_attributes = {
            CONF_WORKDAYS: workdays,
            CONF_EXCLUDES: excludes,
            CONF_EXCLUSION_CALENDARS: exclusion_calendars,
            CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS: trigger_on_any_all_day_events,
            CONF_TRIGGER_ON_EVENT_WORDS: trigger_on_event_words,
            CONF_OFFSET: days_offset,
            CONF_REFRESH_INTERVAL_MINUTES: refresh_interval_minutes,
        }

    def update_data(self, now: datetime) -> None:
        """Get date and look whether it is a holiday."""
        self._attr_is_on = self.date_is_workday(now)
