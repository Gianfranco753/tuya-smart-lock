"""Auto-lock time number entity for Tuya Smart Lock."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)


class TuyaLockAutoLockTime(CoordinatorEntity, NumberEntity):
    """Sets the delay (in seconds) before the lock re-engages after unlocking.

    Reads the current value from the status coordinator (updated in real time
    via Pulsar). Writes via the standard Tuya device command endpoint.
    The entity is unavailable if the lock doesn't report this datapoint.
    """

    _attr_has_entity_name = True
    _attr_name = "Auto-lock delay"
    _attr_icon = "mdi:timer-lock-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(
        self, api: TuyaCloudApi, coordinator, device_id: str, device_name: str
    ) -> None:
        super().__init__(coordinator)
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_auto_lock_time"
        self._device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        value = data.get("auto_lock_time")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            success = await self._api.async_send_command(
                self._device_id, "auto_lock_time", int(value)
            )
        except (TuyaApiError, ConnectionError) as err:
            raise HomeAssistantError(f"Could not set auto-lock delay: {err}") from err

        if not success:
            raise HomeAssistantError("Tuya rejected the auto-lock delay command")
