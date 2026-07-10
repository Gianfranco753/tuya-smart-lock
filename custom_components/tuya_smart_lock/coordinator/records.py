"""Coordinator that polls unlock/alarm records."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

RECORDS_UPDATE_INTERVAL = timedelta(minutes=2)


class TuyaLockRecordsCoordinator(DataUpdateCoordinator[list]):
    """Polls the most recent unlock/alarm records for the lock.

    Tuya's records API is poll-based, not push — new unlocks are detected
    at most RECORDS_UPDATE_INTERVAL after they happen, not instantly.
    """

    def __init__(self, hass: HomeAssistant, api: TuyaCloudApi, device_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"tuya_smart_lock_records_{device_id}",
            update_interval=RECORDS_UPDATE_INTERVAL,
        )
        self._api = api
        self._device_id = device_id

    async def _async_update_data(self) -> list:
        """Fetch the most recent unlock records."""
        try:
            return await self._api.async_get_unlock_records(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Tuya Cloud API: {err}") from err
