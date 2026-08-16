"""Coordinator that polls alarm/security event records."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..api import TuyaApiError, TuyaCloudApi

_LOGGER = logging.getLogger(__name__)

ALARM_RECORDS_UPDATE_INTERVAL = timedelta(minutes=10)


class TuyaLockAlarmRecordsCoordinator(DataUpdateCoordinator[list]):
    """Polls recent alarm records (wrong password, hijack, etc.) for the lock."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TuyaCloudApi,
        device_id: str,
        update_interval: timedelta = ALARM_RECORDS_UPDATE_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"tuya_smart_lock_alarm_records_{device_id}",
            update_interval=update_interval,
        )
        self._api = api
        self._device_id = device_id

    async def _async_update_data(self) -> list:
        try:
            return await self._api.async_get_alarm_records(self._device_id)
        except (TuyaApiError, ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with Tuya Cloud API: {err}") from err
