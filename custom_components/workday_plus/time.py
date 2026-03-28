"""Time entities for Workday Plus alarm settings."""

from __future__ import annotations

from datetime import time

from holidays import __version__ as python_holidays_version

from homeassistant.components.time import TimeEntity
from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import WorkdayConfigEntry
from .const import (
    DEFAULT_NAME,
    DEFAULT_OFFDAY_ALARM_TIME,
    DEFAULT_WORKDAY_ALARM_TIME,
    DOMAIN,
)


async def async_setup_entry(
    hass,
    entry: WorkdayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Workday Plus alarm time entities."""
    device_name = entry.options.get(CONF_NAME, DEFAULT_NAME)

    async_add_entities(
        [
            WorkdayAlarmTimeEntity(
                entry_id=entry.entry_id,
                device_name=device_name,
                unique_id_suffix="workday_alarm_time",
                translation_key="workday_alarm",
                default_value=DEFAULT_WORKDAY_ALARM_TIME,
            ),
            WorkdayAlarmTimeEntity(
                entry_id=entry.entry_id,
                device_name=device_name,
                unique_id_suffix="offday_alarm_time",
                translation_key="offday_alarm",
                default_value=DEFAULT_OFFDAY_ALARM_TIME,
            ),
        ]
    )


class WorkdayAlarmTimeEntity(TimeEntity, RestoreEntity):
    """A restore-capable alarm time entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        *,
        entry_id: str,
        device_name: str,
        unique_id_suffix: str,
        translation_key: str,
        default_value: time,
    ) -> None:
        """Initialize the alarm time entity."""
        self._attr_unique_id = f"{entry_id}_{unique_id_suffix}"
        self._attr_translation_key = translation_key
        self._attr_native_value = default_value
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="python-holidays",
            model=python_holidays_version,
            name=device_name,
        )

    async def async_added_to_hass(self) -> None:
        """Restore previous value if available."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return

        if last_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        if (parsed_time := dt_util.parse_time(last_state.state)) is not None:
            self._attr_native_value = parsed_time

    async def async_set_value(self, value: time) -> None:
        """Update the alarm time value."""
        self._attr_native_value = value
        self.async_write_ha_state()
