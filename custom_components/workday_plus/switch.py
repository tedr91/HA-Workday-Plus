"""Switch entities for Workday Plus alarm settings."""

from __future__ import annotations

from holidays import __version__ as python_holidays_version

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME, STATE_ON
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import WorkdayConfigEntry
from .const import (
    DEFAULT_NAME,
    DEFAULT_OFFDAY_ALARM_ENABLED,
    DEFAULT_WORKDAY_ALARM_ENABLED,
    DOMAIN,
)


async def async_setup_entry(
    hass,
    entry: WorkdayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Workday Plus alarm enabled switch entities."""
    device_name = entry.options.get(CONF_NAME, DEFAULT_NAME)

    async_add_entities(
        [
            WorkdayAlarmEnabledSwitchEntity(
                entry_id=entry.entry_id,
                device_name=device_name,
                unique_id_suffix="workday_alarm_enabled",
                translation_key="workday_alarm_enabled",
                default_is_on=DEFAULT_WORKDAY_ALARM_ENABLED,
            ),
            WorkdayAlarmEnabledSwitchEntity(
                entry_id=entry.entry_id,
                device_name=device_name,
                unique_id_suffix="offday_alarm_enabled",
                translation_key="offday_alarm_enabled",
                default_is_on=DEFAULT_OFFDAY_ALARM_ENABLED,
            ),
        ]
    )


class WorkdayAlarmEnabledSwitchEntity(SwitchEntity, RestoreEntity):
    """A restore-capable alarm enabled switch entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        *,
        entry_id: str,
        device_name: str,
        unique_id_suffix: str,
        translation_key: str,
        default_is_on: bool,
    ) -> None:
        """Initialize the alarm enabled switch entity."""
        self._attr_unique_id = f"{entry_id}_{unique_id_suffix}"
        self._attr_translation_key = translation_key
        self._attr_is_on = default_is_on
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="python-holidays",
            model=python_holidays_version,
            name=device_name,
        )

    async def async_added_to_hass(self) -> None:
        """Restore previous state if available."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return
        self._attr_is_on = last_state.state == STATE_ON

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        self.async_write_ha_state()
