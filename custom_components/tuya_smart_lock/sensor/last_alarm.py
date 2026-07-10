"""Last alarm sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockLastAlarm(CoordinatorEntity, SensorEntity):
    """Last alarm/error condition reported by the lock (e.g. wrong_password)."""

    _attr_has_entity_name = True
    _attr_name = "Last alarm"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_last_alarm"
        self._device_name = device_name

    @property
    def device_info(self):
        """Link to the same device as the lock entity."""
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def native_value(self):
        """Return the last reported alarm code, if any."""
        data = self.coordinator.data or {}
        return data.get("alarm_lock")
