"""Sensor platform for Tuya Smart Lock: battery, temp passwords, last alarm."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN
from .battery import TuyaLockBattery
from .last_alarm import TuyaLockLastAlarm
from .temp_passwords import TuyaLockTempPasswords

_LOGGER = logging.getLogger(__name__)


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
        TuyaLockLastAlarm(status_coordinator, device_id, device_name),
    ])
s