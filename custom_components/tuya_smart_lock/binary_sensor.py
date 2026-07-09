"""Binary sensors for Tuya Smart Lock (tamper, doorbell)."""

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    entry_data = data["entry_data"]
    status_coordinator = data["status_coordinator"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    async_add_entities([
        TuyaLockTamper(status_coordinator, device_id, device_name),
        TuyaLockDoorbell(status_coordinator, device_id, device_name),
    ])


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
