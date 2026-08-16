"""Remote unlock enabled/disabled sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockRemoteUnlockEnabled(CoordinatorEntity, BinarySensorEntity):
    """Reports whether remote unlock is currently enabled on the device.

    If this turns off while HA thinks it can control the lock, all lock/unlock
    commands will silently fail at the device level. Surfacing it lets you
    build a watchdog automation.
    """

    _attr_has_entity_name = True
    _attr_name = "Remote unlock enabled"
    _attr_icon = "mdi:remote"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_remote_unlock_enabled"
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
        return bool(data.get("remote_unlock_switch", False))
