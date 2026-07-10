"""Temporary passwords list sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

PHASE_LABELS = {
    1: "pending_creation",
    2: "normal",
    3: "frozen",
    4: "deleted",
    5: "creation_failed",
}


class TuyaLockTempPasswords(CoordinatorEntity, SensorEntity):
    """Sensor exposing the list of temporary passwords configured on the lock.

    The state is the count of active (non-deleted) passwords. The full list
    is available as the 'passwords' extra state attribute.
    """

    _attr_has_entity_name = True
    _attr_name = "Temporary passwords"
    _attr_icon = "mdi:key-variant"

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_temp_passwords"
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
    def _active_passwords(self) -> list[dict]:
        passwords = self.coordinator.data or []
        return [p for p in passwords if p.get("phase") != 4]  # 4 = deleted

    @property
    def native_value(self):
        """Return the count of active passwords."""
        return len(self._active_passwords)

    @property
    def extra_state_attributes(self):
        """Return the full list of active passwords."""
        return {
            "passwords": [
                {
                    "password_id": p.get("password_id"),
                    "name": p.get("name"),
                    "phase": PHASE_LABELS.get(p.get("phase"), p.get("phase")),
                    "effective_time": p.get("effective_time"),
                    "invalid_time": p.get("invalid_time"),
                }
                for p in self._active_passwords
            ]
        }
