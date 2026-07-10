"""Doorbell binary sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockDoorbell(CoordinatorEntity, BinarySensorEntity):
    """Doorbell state for a Tuya smart lock.

    Note: this is poll-based (shares status_coordinator's 5-min interval),
    so brief doorbell presses between polls may be missed.
    """

    _attr_has_entity_name = True
    _attr_name = "Doorbell"
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_doorbell"
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
    def is_on(self) -> bool:
        """Return True if the doorbell was recently pressed."""
        data = self.coordinator.data or {}
        return bool(data.get("doorbell", False))
