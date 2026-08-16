"""Diagnostics support for Tuya Smart Lock."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ACCESS_SECRET, DOMAIN

_TO_REDACT = {CONF_ACCESS_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    status_coordinator = data["status_coordinator"]
    records_coordinator = data["records_coordinator"]
    temp_passwords_coordinator = data["temp_passwords_coordinator"]
    alarm_records_coordinator = data["alarm_records_coordinator"]

    return {
        "entry": async_redact_data(dict(entry.data), _TO_REDACT),
        "options": dict(entry.options),
        "device_details": data.get("device_details", {}),
        "coordinators": {
            "status": {
                "last_update_success": status_coordinator.last_update_success,
                "data": status_coordinator.data,
            },
            "records": {
                "last_update_success": records_coordinator.last_update_success,
                "record_count": len(records_coordinator.data or []),
            },
            "temp_passwords": {
                "last_update_success": temp_passwords_coordinator.last_update_success,
                "password_count": len(temp_passwords_coordinator.data or []),
            },
            "alarm_records": {
                "last_update_success": alarm_records_coordinator.last_update_success,
                "record_count": len(alarm_records_coordinator.data or []),
            },
        },
    }
