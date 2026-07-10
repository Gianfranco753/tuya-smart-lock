"""Unlock/alarm history records."""

import logging

from ..const import RECORDS_ENDPOINT
from .client import TuyaApiError

_LOGGER = logging.getLogger(__name__)


class RecordsMixin:
    """Adds the unlock/alarm records endpoint to TuyaCloudApi."""

    async def async_get_unlock_records(self, device_id: str, page_size: int = 5) -> list[dict]:
        """Get the most recent unlock/alarm records for a device."""
        path = RECORDS_ENDPOINT.format(device_id=device_id)
        path += f"?pageNo=1&pageSize={page_size}&startTime=0&endTime=0"
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to get unlock records: %s", resp.get("msg"))
            raise TuyaApiError(f"Tuya returned an error: {resp.get('msg')}")

        return resp.get("result", {}).get("records", [])
