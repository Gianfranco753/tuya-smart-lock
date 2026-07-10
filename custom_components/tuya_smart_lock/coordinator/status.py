"""Coordinator that polls the lock's full device status."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

STATUS_UPDATE_INTERVAL = timedelta(minutes=5)


class TuyaLockStatusCoordinator(DataUpdateCoordinator[dict]):
    """Polls the lock's full device status once and shares it across
    battery, tamper, doorbell, alarm, and any other status-derived entities.
    """

    def __init__(self, hass: HomeAssistant, api: TuyaCloudApi, device_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"tuya_smart_lock_status_{device_id}",
            update_interval=STATUS_UPDATE_INTERVAL,
        )
        self._api = api
        self._device_id = device_id

    async def _async_update_data(self) -> dict:
        """Fetch the latest status and return it as a {code: value} dict."""
        try:
            raw = await self._api.async_get_status(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Tuya Cloud API: {err}") from err

        return {dp["code"]: dp["value"] for dp in raw}
