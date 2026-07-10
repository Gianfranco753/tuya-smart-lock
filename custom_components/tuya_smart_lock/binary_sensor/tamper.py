"""Tamper/hijack binary sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockTamper(CoordinatorEntity, BinarySensorEntity):
    """Tamper/hijack alert for a Tuya smart lock."""

    _attr_has_entity_name = True
    _attr_name = "Tamper"
    _attr_device_class = BinarySensorDeviceClass.TAMPER
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_tamper"
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
        """Return True if the lock reports a hijack/tamper alert."""
        data = self.coordinator.data or {}
        return bool(data.get("hijack", False))
