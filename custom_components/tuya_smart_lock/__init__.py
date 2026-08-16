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
from .api import TuyaCloudApi
from .pulsar import TuyaOpenPulsar

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

    pulsar = TuyaOpenPulsar(
        access_id=entry.data[CONF_ACCESS_ID],
        access_secret=entry.data[CONF_ACCESS_SECRET],
        region=entry.data[CONF_API_REGION],
    )
    pulsar.add_message_handler(
        _make_pulsar_handler(hass, device_id, status_coordinator, records_coordinator)
    )
    await pulsar.start()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "entry_data": entry.data,
        "status_coordinator": status_coordinator,
        "temp_passwords_coordinator": temp_passwords_coordinator,
        "records_coordinator": records_coordinator,
        "pulsar": pulsar,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    pulsar: TuyaOpenPulsar | None = entry_data.get("pulsar")
    if pulsar:
        await pulsar.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# DP codes that indicate someone actually used the lock — triggers a records
# refresh so the unlock history event entity fires with full detail (user name
# etc.) within one API round-trip instead of waiting up to 2 minutes.
_UNLOCK_DP_CODES = {
    "unlock_fingerprint",
    "unlock_password",
    "unlock_temporary",
    "unlock_dynamic",
    "unlock_card",
    "unlock_face",
    "unlock_remote",
}


def _make_pulsar_handler(
    hass: HomeAssistant,
    device_id: str,
    status_coordinator: TuyaLockStatusCoordinator,
    records_coordinator: TuyaLockRecordsCoordinator,
):
    """Return an async handler that routes Pulsar messages to the right coordinators."""

    async def _on_message(payload: dict) -> None:
        if payload.get("devId") != device_id:
            return
        if payload.get("bizCode") != "statusReport":
            return

        status_list = _extract_status_list(payload.get("bizData"))
        if not status_list:
            return

        new_status = {dp["code"]: dp["value"] for dp in status_list}
        status_coordinator.async_push_update(new_status)

        if _UNLOCK_DP_CODES & set(new_status):
            await records_coordinator.async_request_refresh()

    return _on_message


def _extract_status_list(biz_data) -> list:
    """Pull the flat [{code, value}] list out of whatever shape bizData arrives in."""
    if isinstance(biz_data, dict):
        return biz_data.get("status", [])
    if isinstance(biz_data, list):
        for item in biz_data:
            if isinstance(item, dict) and "status" in item:
                return item["status"]
    return []
