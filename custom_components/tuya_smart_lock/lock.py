"""Lock entity for Tuya Smart Lock."""

import asyncio
import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN
from .api import TuyaCloudApi, TuyaApiError

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
    status_coordinator = data["status_coordinator"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    device_details = hass.data[DOMAIN][entry.entry_id].get("device_details", {})

    async_add_entities([TuyaSmartLock(api, status_coordinator, device_id, device_name, device_details)])

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
    platform.async_register_entity_service(
        "get_dynamic_password",
        {},
        "async_get_dynamic_password",
        supports_response=SupportsResponse.ONLY,
    )
    platform.async_register_entity_service(
        "delete_temp_password",
        {vol.Required("password_id"): str},
        "async_delete_temp_password",
    )
    platform.async_register_entity_service(
        "freeze_temp_password",
        {vol.Required("password_id"): str},
        "async_freeze_temp_password",
    )
    platform.async_register_entity_service(
        "unfreeze_temp_password",
        {vol.Required("password_id"): str},
        "async_unfreeze_temp_password",
    )


def _is_open(value) -> bool:
    """Interpret a Tuya open_close datapoint value as True=open/unlocked."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "open"
    return bool(value)


class TuyaSmartLock(CoordinatorEntity, LockEntity):
    """Lock entity that controls a Tuya smart lock via Cloud API.

    Subscribes to status_coordinator so that physical unlocks (fingerprint,
    card, app) are reflected in HA in real time via the open_close datapoint,
    pushed by the Pulsar client or picked up on the next poll.
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, api, coordinator, device_id: str, device_name: str, device_details: dict) -> None:
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._device_details = device_details
        self._attr_unique_id = f"tuya_smart_lock_{device_id}"
        self._attr_is_locked = True
        self._attr_is_locking = False
        self._attr_is_unlocking = False
        self._device_name = device_name
        self._relock_handle: asyncio.TimerHandle | None = None

    @property
    def device_info(self):
        """Link to the existing Tuya device if present, otherwise create our own."""
        info = {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }
        if self._device_details:
            model = self._device_details.get("model") or self._device_details.get("product_name")
            if model:
                info["model"] = model
            if fw := self._device_details.get("firmware_ver"):
                info["sw_version"] = fw
            if hw := self._device_details.get("hw_ver"):
                info["hw_version"] = hw
        return info

    def _handle_coordinator_update(self) -> None:
        """Sync lock state from the device's open_close datapoint.

        Skipped during an in-progress lock/unlock command so that the
        optimistic transition state isn't overwritten mid-command.
        """
        command_in_progress = self._attr_is_locking or self._attr_is_unlocking
        if not command_in_progress:
            data = self.coordinator.data or {}
            _LOGGER.debug("Lock coordinator data keys: %s", list(data.keys()))
            open_close = data.get("open_close")
            if open_close is not None:
                self._attr_is_locked = not _is_open(open_close)
                _LOGGER.debug("open_close=%s → is_locked=%s", open_close, self._attr_is_locked)
            else:
                _LOGGER.debug("open_close not in coordinator data, is_locked unchanged (%s)", self._attr_is_locked)
        self.async_write_ha_state()

    async def async_lock(self, **kwargs) -> None:
        """Lock the door."""
        _LOGGER.debug("Lock command issued for %s", self._device_id)
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
        _LOGGER.debug("Unlock command issued for %s", self._device_id)
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
            # After the hardware's auto-lock delay, poll the actual bolt state
            # rather than guessing. A blind optimistic set-to-locked would be
            # overridden by the next coordinator poll anyway if the bolt hasn't
            # engaged yet, creating a confusing flip.
            auto_lock_time = (self.coordinator.data or {}).get(
                "auto_lock_time", DEFAULT_AUTO_LOCK_DELAY
            )
            _LOGGER.debug(
                "Unlock succeeded; scheduling status refresh in %ss (auto_lock_time=%s)",
                auto_lock_time + 1,
                auto_lock_time,
            )
            if self._relock_handle is not None:
                self._relock_handle.cancel()
            self._relock_handle = self.hass.loop.call_later(
                auto_lock_time + 1, self._schedule_status_refresh
            )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending relock timer when the entity is removed."""
        await super().async_will_remove_from_hass()
        if self._relock_handle is not None:
            self._relock_handle.cancel()
            self._relock_handle = None

    def _schedule_status_refresh(self) -> None:
        """After the auto-lock delay, fetch the real bolt state from the hardware."""
        _LOGGER.debug("Auto-lock window elapsed, requesting status refresh for %s", self._device_id)
        self._relock_handle = None
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def async_create_temp_password(self, code: str, name: str, duration_hours: int) -> None:
        """Create a temporary password on the lock."""
        if not code.isdigit():
            raise HomeAssistantError("Password code must be numeric")

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

    async def async_get_dynamic_password(self) -> ServiceResponse:
        """Get a dynamic password. Valid ~5 minutes, works even if the lock is offline."""
        try:
            password = await self._api.async_get_dynamic_password(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not get dynamic password: {err}") from err

        if not password:
            raise HomeAssistantError("Tuya did not return a dynamic password")

        return {"dynamic_password": password}

    async def async_delete_temp_password(self, password_id: str) -> None:
        """Delete a temporary password from the lock."""
        try:
            success = await self._api.async_delete_temp_password(self._device_id, password_id)
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not delete password '{password_id}': {err}") from err

        if not success:
            raise HomeAssistantError(f"Failed to delete password '{password_id}'")

    async def async_freeze_temp_password(self, password_id: str) -> None:
        """Freeze a temporary password (Zigbee locks only)."""
        try:
            success = await self._api.async_freeze_temp_password(self._device_id, password_id)
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not freeze password '{password_id}': {err}") from err

        if not success:
            raise HomeAssistantError(f"Failed to freeze password '{password_id}'")

    async def async_unfreeze_temp_password(self, password_id: str) -> None:
        """Unfreeze a temporary password (Zigbee locks only)."""
        try:
            success = await self._api.async_unfreeze_temp_password(self._device_id, password_id)
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not unfreeze password '{password_id}': {err}") from err

        if not success:
            raise HomeAssistantError(f"Failed to unfreeze password '{password_id}'")
