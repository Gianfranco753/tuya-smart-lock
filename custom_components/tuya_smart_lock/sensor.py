"""Battery sensor for Tuya Smart Lock."""

import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=12)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up battery sensor from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    entry_data = data["entry_data"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    async_add_entities([TuyaLockBattery(api, device_id, device_name)])


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

    async def async_update(self) -> None:
        """Fetch the latest battery level."""
        try:
            level = await self._api.async_get_battery_level(self._device_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not update battery level for %s: %s", self._device_id, err)
            return

        if level is not None:
            self._attr_native_value = level
