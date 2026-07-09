"""Battery and temporary password sensors for Tuya Smart Lock."""

import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Shared polling interval for all sensors in this platform.
SCAN_INTERVAL = timedelta(hours=1)

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
    api = data["api"]
    entry_data = data["entry_data"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    async_add_entities([
        TuyaLockBattery(api, device_id, device_name),
        TuyaLockTempPasswords(api, device_id, device_name),
    ])


class TuyaLockBattery(SensorEntity):
    """Battery level sensor for a Tuya smart lock."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_should_poll = True

    def __init__(self, api, device_id: str, device_name: str) -> None:
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_battery"
        self._attr_native_value = None
        self._device_name = device_name

    @property
    def device_info(self):
        """Link to the same device as the lock entity."""
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    async def async_added_to_hass(self) -> None:
        """Do an initial fetch immediately instead of waiting for the first poll."""
        await self.async_update()

    async def async_update(self) -> None:
        """Fetch the latest battery level."""
        try:
            level = await self._api.async_get_battery_level(self._device_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not update battery level for %s: %s", self._device_id, err)
            return

        if level is not None:
            self._attr_native_value = level


class TuyaLockTempPasswords(SensorEntity):
    """Sensor exposing the list of temporary passwords configured on the lock.

    The state is the count of active (non-deleted) passwords. The full list,
    with password_id/name/phase/effective_time/invalid_time for each, is
    available as the 'passwords' extra state attribute.
    """

    _attr_has_entity_name = True
    _attr_name = "Temporary passwords"
    _attr_icon = "mdi:key-variant"
    _attr_should_poll = True

    def __init__(self, api, device_id: str, device_name: str) -> None:
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_temp_passwords"
        self._attr_native_value = None
        self._attr_extra_state_attributes = {"passwords": []}
        self._device_name = device_name

    @property
    def device_info(self):
        """Link to the same device as the lock entity."""
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    async def async_added_to_hass(self) -> None:
        """Do an initial fetch immediately instead of waiting for the first poll."""
        await self.async_update()

    async def async_update(self) -> None:
        """Fetch the latest list of temporary passwords."""
        try:
            passwords = await self._api.async_list_temp_passwords(self._device_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not update temp passwords for %s: %s", self._device_id, err)
            return

        active = [p for p in passwords if p.get("phase") != 4]  # 4 = deleted

        self._attr_native_value = len(active)
        self._attr_extra_state_attributes = {
            "passwords": [
                {
                    "password_id": p.get("password_id"),
                    "name": p.get("name"),
                    "phase": PHASE_LABELS.get(p.get("phase"), p.get("phase")),
                    "effective_time": p.get("effective_time"),
                    "invalid_time": p.get("invalid_time"),
                }
                for p in active
            ]
        }
