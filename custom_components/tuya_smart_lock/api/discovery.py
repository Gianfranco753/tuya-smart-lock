"""Credential testing and device discovery."""

import logging

from ..const import LOCK_CATEGORIES

_LOGGER = logging.getLogger(__name__)


class DiscoveryMixin:
    """Adds credential testing and lock device discovery to TuyaCloudApi."""

    async def async_test_credentials(self) -> bool:
        """Test if the credentials are valid.

        Raises TuyaApiError if the network itself fails, so the caller
        can tell "wrong credentials" apart from "cannot reach Tuya cloud".
        """
        self._token = None
        self._token_expiry = 0
        try:
            await self._ensure_token()
            return True
        except ConnectionError:
            return False

    async def async_discover_devices(self) -> list[dict]:
        """Discover lock devices linked to this account."""
        await self._ensure_token()

        # Use the associated-users endpoint which lists all devices linked via the app
        resp = await self._request("GET", "/v1.0/iot-01/associated-users/devices")

        if not resp.get("success"):
            _LOGGER.error("Failed to list devices: %s", resp.get("msg"))
            return []

        result = resp.get("result", {})
        all_devices = result.get("devices", result) if isinstance(result, dict) else result

        devices = []
        for device in all_devices:
            category = device.get("category", "")
            if category in LOCK_CATEGORIES:
                devices.append({
                    "id": device["id"],
                    "name": device.get("name", device["id"]),
                    "category": category,
                    "model": device.get("model", ""),
                    "product_name": device.get("product_name", ""),
                })

        return devices
