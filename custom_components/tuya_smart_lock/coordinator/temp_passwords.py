"""Coordinator that polls the list of temporary passwords."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

TEMP_PASSWORDS_UPDATE_INTERVAL = timedelta(hours=1)


class TuyaLockTempPasswordsCoordinator(DataUpdateCoordinator[list]):
    """Polls the list of temporary passwords configured on the lock."""

    def __init__(self, hass: HomeAssistant, api: TuyaCloudApi, device_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"tuya_smart_lock_temp_passwords_{device_id}",
            update_interval=TEMP_PASSWORDS_UPDATE_INTERVAL,
        )
        self._api = api
        self._device_id = device_id

    async def _async_update_data(self) -> list:
        """Fetch the latest list of temporary passwords."""
        try:
            return await self._api.async_list_temp_passwords(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Tuya Cloud API: {err}") from err
