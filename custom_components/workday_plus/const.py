"""Add constants for Workday integration."""

from __future__ import annotations

import logging

from homeassistant.const import WEEKDAYS, Platform

LOGGER = logging.getLogger(__package__)

ALLOWED_DAYS = [*WEEKDAYS, "holiday"]

DOMAIN = "workday_plus"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR]

CONF_PROVINCE = "province"
CONF_WORKDAYS = "workdays"
CONF_EXCLUDES = "excludes"
CONF_OFFSET = "days_offset"
CONF_ADD_HOLIDAYS = "add_holidays"
CONF_REMOVE_HOLIDAYS = "remove_holidays"
CONF_CATEGORY = "category"
CONF_EXCLUSION_CALENDARS = "exclusion_calendars"
CONF_EXCLUSION_CALENDAR_RULES = "exclusion_calendar_rules"
CONF_REFRESH_INTERVAL_MINUTES = "refresh_interval_minutes"
CONF_TRIGGER_ON_ANY_ALL_DAY_EVENTS = "trigger_on_any_all_day_events"
CONF_TRIGGER_ON_EVENT_WORDS = "trigger_on_event_words"

# By default, Monday - Friday are workdays
DEFAULT_WORKDAYS = ["mon", "tue", "wed", "thu", "fri"]
# By default, public holidays, Saturdays and Sundays are excluded from workdays
DEFAULT_EXCLUDES = ["sat", "sun", "holiday"]
DEFAULT_NAME = "Workday Plus Sensor"
DEFAULT_OFFSET = 0
DEFAULT_EXCLUSION_CALENDAR_RULES: dict[str, dict[str, bool | list[str]]] = {}
DEFAULT_REFRESH_INTERVAL_MINUTES = 30
DEFAULT_TRIGGER_ON_ANY_ALL_DAY_EVENTS = True
DEFAULT_TRIGGER_ON_EVENT_WORDS: list[str] = []
