"""Fingerprint attempt count sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockFingerInputTimes(CoordinatorEntity, SensorEntity):
    """Running count of fingerprint scan attempts reported by the lock."""

    _attr_has_entity_name = True
    _attr_name = "Fingerprint attempts"
    _attr_icon = "mdi:fingerprint"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_finger_input_times"
        self._device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        data = self.coordinator.data or {}
        return "finger_input_times" in data

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("finger_input_times")
