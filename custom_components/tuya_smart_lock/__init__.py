"""Tuya Smart Lock integration."""

import logging
from datetime import timedelta

from homeassistant.components.persistent_notification import async_create as pn_create
from homeassistant.components.persistent_notification import async_dismiss as pn_dismiss
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_API_REGION,
    CONF_DEVICE_ID,
    CONF_RECORDS_INTERVAL,
    CONF_STATUS_INTERVAL,
    DOMAIN,
    SIGNAL_LOCK_ALARM,
)
from .coordinator import (
    TuyaLockAlarmRecordsCoordinator,
    TuyaLockRecordsCoordinator,
    TuyaLockStatusCoordinator,
    TuyaLockTempPasswordsCoordinator,
)
from .api import TuyaCloudApi
from .pulsar import TuyaOpenPulsar

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.LOCK,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SWITCH,
    Platform.NUMBER,
]

_PULSAR_DISCONNECT_NOTIFICATION_ID = "tuya_smart_lock_pulsar_disconnected_{}"

_UNLOCK_DP_CODES = {
    "unlock_fingerprint",
    "unlock_password",
    "unlock_temporary",
    "unlock_dynamic",
    "unlock_card",
    "unlock_face",
    "unlock_remote",
}

_PASSWORD_MGMT_DP_CODES = {
    "password_creat",
    "password_delete",
    "password_update",
    "password_disable",
    "password_enable",
    "password_reset",
    "unlock_method_create",
    "unlock_method_delete",
    "update_all_finger",
    "update_all_password",
    "update_all_card",
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tuya Smart Lock from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = TuyaCloudApi(
        access_id=entry.data[CONF_ACCESS_ID],
        access_secret=entry.data[CONF_ACCESS_SECRET],
        region=entry.data[CONF_API_REGION],
        hass=hass,
    )
    device_id = entry.data[CONF_DEVICE_ID]

    status_interval = timedelta(minutes=entry.options.get(CONF_STATUS_INTERVAL, 5))
    records_interval = timedelta(minutes=entry.options.get(CONF_RECORDS_INTERVAL, 2))

    status_coordinator = TuyaLockStatusCoordinator(hass, api, device_id, status_interval)
    temp_passwords_coordinator = TuyaLockTempPasswordsCoordinator(hass, api, device_id)
    records_coordinator = TuyaLockRecordsCoordinator(hass, api, device_id, records_interval)
    alarm_records_coordinator = TuyaLockAlarmRecordsCoordinator(hass, api, device_id)

    await status_coordinator.async_config_entry_first_refresh()
    await temp_passwords_coordinator.async_config_entry_first_refresh()
    await records_coordinator.async_config_entry_first_refresh()
    await alarm_records_coordinator.async_config_entry_first_refresh()

    # Fetch static device details (model, firmware) for the device card.
    # Non-critical: a failure here is logged but doesn't block setup.
    try:
        device_details = await api.async_get_device_details(device_id)
    except Exception:
        _LOGGER.warning("Could not fetch device details for %s", device_id)
        device_details = {}

    notification_id = _PULSAR_DISCONNECT_NOTIFICATION_ID.format(entry.entry_id)

    pulsar = TuyaOpenPulsar(
        access_id=entry.data[CONF_ACCESS_ID],
        access_secret=entry.data[CONF_ACCESS_SECRET],
        region=entry.data[CONF_API_REGION],
        hass=hass,
        on_max_backoff=_make_disconnect_callback(hass, notification_id),
        on_reconnect=_make_reconnect_callback(hass, notification_id),
    )
    pulsar.add_message_handler(
        _make_pulsar_handler(
            hass, device_id, status_coordinator, records_coordinator, temp_passwords_coordinator
        )
    )
    await pulsar.start()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "entry_data": entry.data,
        "device_details": device_details,
        "status_coordinator": status_coordinator,
        "temp_passwords_coordinator": temp_passwords_coordinator,
        "records_coordinator": records_coordinator,
        "alarm_records_coordinator": alarm_records_coordinator,
        "pulsar": pulsar,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the entry when the user saves new options so coordinators
    # restart with the updated polling intervals.
    entry.async_on_unload(
        entry.add_update_listener(
            lambda h, e: h.config_entries.async_reload(e.entry_id)
        )
    )

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


def _make_pulsar_handler(
    hass: HomeAssistant,
    device_id: str,
    status_coordinator: TuyaLockStatusCoordinator,
    records_coordinator: TuyaLockRecordsCoordinator,
    temp_passwords_coordinator: TuyaLockTempPasswordsCoordinator,
):
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

        dp_codes = set(new_status)

        if dp_codes & _UNLOCK_DP_CODES:
            await records_coordinator.async_request_refresh()

        if dp_codes & _PASSWORD_MGMT_DP_CODES:
            await temp_passwords_coordinator.async_request_refresh()

        if "alarm_lock" in new_status:
            async_dispatcher_send(
                hass,
                SIGNAL_LOCK_ALARM.format(device_id),
                new_status["alarm_lock"],
            )

    return _on_message


def _extract_status_list(biz_data) -> list:
    if isinstance(biz_data, dict):
        return biz_data.get("status", [])
    if isinstance(biz_data, list):
        for item in biz_data:
            if isinstance(item, dict) and "status" in item:
                return item["status"]
    return []


@callback
def _make_disconnect_callback(hass: HomeAssistant, notification_id: str):
    @callback
    def _on_disconnect() -> None:
        pn_create(
            hass,
            (
                "The Tuya Smart Lock real-time connection (Pulsar) could not be "
                "re-established after several attempts. Device events will fall back "
                "to polling until the connection recovers. Check your network and "
                "Tuya IoT Platform credentials."
            ),
            title="Tuya Smart Lock: real-time connection lost",
            notification_id=notification_id,
        )

    return _on_disconnect


@callback
def _make_reconnect_callback(hass: HomeAssistant, notification_id: str):
    @callback
    def _on_reconnect() -> None:
        pn_dismiss(hass, notification_id)

    return _on_reconnect
