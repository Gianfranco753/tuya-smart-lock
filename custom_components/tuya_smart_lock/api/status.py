"""Full device status (battery, tamper, doorbell, alarm, etc.)."""

import logging

from ..const import STATUS_ENDPOINT
from .client import TuyaApiError

_LOGGER = logging.getLogger(__name__)


class StatusMixin:
    """Adds the raw device-status endpoint to TuyaCloudApi."""

    async def async_get_status(self, device_id: str) -> list[dict]:
        """Get the raw list of status datapoints for a device.

        Raises TuyaApiError on failure so DataUpdateCoordinator can convert
        it into UpdateFailed / ConfigEntryNotReady as appropriate.
        """
        path = STATUS_ENDPOINT.format(device_id=device_id)
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to get status: %s", resp.get("msg"))
            raise TuyaApiError(f"Tuya returned an error: {resp.get('msg')}")

        return resp.get("result", [])
