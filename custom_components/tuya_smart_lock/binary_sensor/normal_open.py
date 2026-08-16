"""Normal-open (always-unlocked) mode binary sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockNormalOpen(CoordinatorEntity, BinarySensorEntity):
    """Reports whether the lock is in 'normal open' (always-unlocked) mode.

    When on, the lock stays retracted regardless of the handle — typically
    used during business hours on access-control doors.
    """

    _attr_has_entity_name = True
    _attr_name = "Normal open"
    _attr_icon = "mdi:door-open"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_normal_open"
        self._device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return bool(data.get("normal_open_switch", False))
