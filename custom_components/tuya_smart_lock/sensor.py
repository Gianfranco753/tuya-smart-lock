"""Battery and temporary password sensors for Tuya Smart Lock."""

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

PHASE_LABELS = {
    1: "pending_creation",
    2: "normal",
    3: "frozen",
    4: "deleted",
    5: "creation_failed",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    entry_data = data["entry_data"]
    status_coordinator = data["status_coordinator"]
    temp_passwords_coordinator = data["temp_passwords_coordinator"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    async_add_entities([
        TuyaLockBattery(status_coordinator, device_id, device_name),
        TuyaLockTempPasswords(temp_passwords_coordinator, device_id, device_name),
    ])
    async_add_entities([
        TuyaLockBattery(status_coordinator, device_id, device_name),
        TuyaLockTempPasswords(temp_passwords_coordinator, device_id, device_name),
        TuyaLockLastAlarm(status_coordinator, device_id, device_name),
    ])


class TuyaLockBattery(CoordinatorEntity, SensorEntity):
    """Battery level sensor for a Tuya smart lock."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_battery"
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
        """Return the battery percentage from the shared status data."""
        data = self.coordinator.data or {}
        return data.get("battery_percentage", data.get("residual_electricity"))


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
