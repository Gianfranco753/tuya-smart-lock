"""Anti-lock binary sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockAntiLock(CoordinatorEntity, BinarySensorEntity):
    """Reports whether the anti-lock-from-outside feature is engaged.

    When on, the outside handle/keypad is blocked — the door can only be
    opened from the inside. Useful as a 'do not disturb' indicator.
    """

    _attr_has_entity_name = True
    _attr_name = "Anti-lock"
    _attr_device_class = BinarySensorDeviceClass.LOCK
    _attr_icon = "mdi:door-closed-lock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_anti_lock"
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
        return bool(data.get("anti_lock_outside", False))
