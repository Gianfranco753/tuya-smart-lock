"""Tuya Smart Lock integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_ID, CONF_ACCESS_SECRET, CONF_API_REGION, CONF_DEVICE_ID, DOMAIN
from .coordinator import (
    TuyaLockRecordsCoordinator,
    TuyaLockStatusCoordinator,
    TuyaLockTempPasswordsCoordinator,
)
from .tuya_api import TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LOCK, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Smart Lock from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = TuyaCloudApi(
        access_id=entry.data[CONF_ACCESS_ID],
        access_secret=entry.data[CONF_ACCESS_SECRET],
        region=entry.data[CONF_API_REGION],
    )
    device_id = entry.data[CONF_DEVICE_ID]

    status_coordinator = TuyaLockStatusCoordinator(hass, api, device_id)
    temp_passwords_coordinator = TuyaLockTempPasswordsCoordinator(hass, api, device_id)
    records_coordinator = TuyaLockRecordsCoordinator(hass, api, device_id)

    await status_coordinator.async_config_entry_first_refresh()
    await temp_passwords_coordinator.async_config_entry_first_refresh()
    await records_coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "entry_data": entry.data,
        "status_coordinator": status_coordinator,
        "temp_passwords_coordinator": temp_passwords_coordinator,
        "records_coordinator": records_coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok