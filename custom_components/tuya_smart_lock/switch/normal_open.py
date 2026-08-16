"""Normal-open (always-unlocked) mode switch for Tuya Smart Lock."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)


class TuyaLockNormalOpenSwitch(CoordinatorEntity, SwitchEntity):
    """Toggles the lock's 'normal open' (always-unlocked) mode.

    When on, the lock stays retracted regardless of the handle — typically
    used during business hours on access-control doors.
    """

    _attr_has_entity_name = True
    _attr_name = "Normal open"
    _attr_icon = "mdi:door-open"

    def __init__(
        self, api: TuyaCloudApi, coordinator, device_id: str, device_name: str
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_normal_open"
        self._device_name = device_name
        self._optimistic_on: bool | None = None

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def is_on(self) -> bool:
        if self._optimistic_on is not None:
            return self._optimistic_on
        data = self.coordinator.data or {}
        return bool(data.get("normal_open_switch", False))

    def _handle_coordinator_update(self) -> None:
        self._optimistic_on = None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._send("normal_open_switch", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._send("normal_open_switch", False)

    async def _send(self, code: str, value: bool) -> None:
        try:
            success = await self._api.async_send_command(self._device_id, code, value)
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not set normal open mode: {err}") from err

        if not success:
            raise HomeAssistantError("Tuya rejected the normal open command")

        self._optimistic_on = value
        self.async_write_ha_state()
