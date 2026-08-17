"""Coordinator that polls the lock's full device status."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

STATUS_UPDATE_INTERVAL = timedelta(minutes=5)


class TuyaLockStatusCoordinator(DataUpdateCoordinator[dict]):
    """Polls the lock's full device status once and shares it across
    battery, tamper, doorbell, alarm, and any other status-derived entities.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: TuyaCloudApi,
        device_id: str,
        update_interval: timedelta = STATUS_UPDATE_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"tuya_smart_lock_status_{device_id}",
            update_interval=update_interval,
        )
        self._api = api
        self._device_id = device_id

    async def _async_update_data(self) -> dict:
        """Fetch the latest status and return it as a {code: value} dict."""
        try:
            raw = await self._api.async_get_status(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Tuya Cloud API: {err}") from err

        data = {dp["code"]: dp["value"] for dp in raw}
        _LOGGER.debug("Status data: %s", data)
        return data

    @callback
    def async_push_update(self, new_data: dict) -> None:
        """Apply a partial status update received via Pulsar without polling."""
        merged = {**(self.data or {}), **new_data}
        # async_set_updated_data also resets last_update_success=True, so entities
        # that went unavailable after a failed poll recover on the next push event.
        self.async_set_updated_data(merged)
