"""Binary sensor platform for Tuya Smart Lock."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN
from .anti_lock import TuyaLockAntiLock
from .doorbell import TuyaLockDoorbell
from .remote_unlock_switch import TuyaLockRemoteUnlockEnabled
from .tamper import TuyaLockTamper

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
        TuyaLockAntiLock(status_coordinator, device_id, device_name),
        TuyaLockRemoteUnlockEnabled(status_coordinator, device_id, device_name),
    ])
