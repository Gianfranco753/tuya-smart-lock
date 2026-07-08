"""Lock entity for Tuya Smart Lock."""

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

from .tuya_api import TuyaApiError

_LOGGER = logging.getLogger(__name__)

DEFAULT_AUTO_LOCK_DELAY = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up lock entity from config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    entry_data = data["entry_data"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    # Read auto_lock_time from device
    try:
        auto_lock_time = await api.async_get_auto_lock_time(device_id)
    except (TuyaApiError, ConnectionError) as err:
        raise ConfigEntryNotReady(f"Cannot reach Tuya Cloud API: {err}") from err

    if auto_lock_time is None:
        auto_lock_time = DEFAULT_AUTO_LOCK_DELAY

    async_add_entities([TuyaSmartLock(api, device_id, device_name, auto_lock_time)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "create_temp_password",
        {
            vol.Required("code"): str,
            vol.Required("name"): str,
            vol.Required("duration_hours"): vol.Coerce(int),
        },
        "async_create_temp_password",
    )

class TuyaSmartLock(LockEntity):
    """Lock entity that controls a Tuya smart lock via Cloud API."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, api, device_id: str, device_name: str, auto_lock_time: int) -> None:
        self._api = api
        self._device_id = device_id
        self._auto_lock_time = auto_lock_time
        self._attr_unique_id = f"tuya_smart_lock_{device_id}"
        self._attr_is_locked = True
        self._attr_is_locking = False
        self._attr_is_unlocking = False
        self._device_name = device_name

    @property
    def device_info(self):
        """Link to the existing Tuya device if present, otherwise create our own."""
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    async def async_lock(self, **kwargs) -> None:
        """Lock the door."""
        self._attr_is_locking = True
        self.async_write_ha_state()

        try:
            success = await self._api.async_lock(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            self._attr_is_locking = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not lock the door: {err}") from err

        self._attr_is_locking = False
        if success:
            self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs) -> None:
        """Unlock the door."""
        self._attr_is_unlocking = True
        self.async_write_ha_state()

        try:
            success = await self._api.async_unlock(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            self._attr_is_unlocking = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not unlock the door: {err}") from err

        self._attr_is_unlocking = False
        if success:
            self._attr_is_locked = False
        self.async_write_ha_state()

        if success:
            # Re-lock after auto_lock_time + 1s buffer
            delay = self._auto_lock_time + 1
            self.hass.loop.call_later(delay, self._set_locked)

    def _set_locked(self) -> None:
        """Reset state to locked after auto-lock delay."""
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_create_temp_password(self, code: str, name: str, duration_hours: int) -> None:
        """Create a temporary password on the lock."""
        if not code.isdigit():
            raise HomeAssistantError("El código debe ser numérico")

        now = dt_util.utcnow()
        effective_time = int(now.timestamp())
        invalid_time = int((now + timedelta(hours=duration_hours)).timestamp())
        
        try:
            success = await self._api.async_create_temp_password(
                self._device_id, code, name, effective_time, invalid_time
            )
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not create temporary password '{name}': {err}") from err
        
        if not success:
            raise HomeAssistantError(f"Failed to create temporary password '{name}'")
