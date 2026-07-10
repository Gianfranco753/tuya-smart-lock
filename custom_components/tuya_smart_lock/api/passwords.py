"""Temporary and dynamic password management."""

import logging

from ..const import (
    DYNAMIC_PASSWORD_ENDPOINT,
    FREEZE_PASSWORD_ENDPOINT,
    TEMP_PASSWORD_DELETE_ENDPOINT,
    TEMP_PASSWORD_ENDPOINT,
    TEMP_PASSWORDS_LIST_ENDPOINT,
    TICKET_ENDPOINT,
    UNFREEZE_PASSWORD_ENDPOINT,
)
from ..crypto import decrypt_ticket_key, encrypt_password

_LOGGER = logging.getLogger(__name__)


class PasswordsMixin:
    """Adds temp/dynamic password endpoints to TuyaCloudApi."""

    async def async_create_temp_password(
        self, device_id: str, password: str, name: str,
        effective_time: int, invalid_time: int,
    ) -> bool:
        """Create a temporary password on the lock."""
        path = TICKET_ENDPOINT.format(device_id=device_id)
        ticket_resp = await self._request("POST", path)
        if not ticket_resp.get("success"):
            _LOGGER.error("Failed to get ticket: %s", ticket_resp.get("msg"))
            return False

        ticket_id = ticket_resp["result"]["ticket_id"]
        ticket_key = ticket_resp["result"]["ticket_key"]

        real_key = decrypt_ticket_key(ticket_key, self._access_secret)
        encrypted_pwd = encrypt_password(password, real_key)

        path = TEMP_PASSWORD_ENDPOINT.format(device_id=device_id)
        resp = await self._request("POST", path, {
            "password": encrypted_pwd,
            "password_type": "ticket",
            "ticket_id": ticket_id,
            "name": name,
            "effective_time": effective_time,
            "invalid_time": invalid_time,
        })

        if not resp.get("success"):
            _LOGGER.error("Failed to create temp password: %s", resp.get("msg"))
            return False

        return True

    async def async_get_dynamic_password(self, device_id: str) -> str | None:
        """Get a short-lived dynamic password (valid ~5 minutes, works offline)."""
        path = DYNAMIC_PASSWORD_ENDPOINT.format(device_id=device_id)
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to get dynamic password: %s", resp.get("msg"))
            return None

        return resp.get("result", {}).get("dynamic_password")

    async def async_list_temp_passwords(self, device_id: str) -> list[dict]:
        """List temporary passwords currently configured on the lock."""
        path = TEMP_PASSWORDS_LIST_ENDPOINT.format(device_id=device_id) + "?valid=true"
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to list temp passwords: %s", resp.get("msg"))
            return []

        return resp.get("result", [])

    async def async_delete_temp_password(self, device_id: str, password_id: str) -> bool:
        """Delete a temporary password from the lock."""
        path = TEMP_PASSWORD_DELETE_ENDPOINT.format(device_id=device_id, password_id=password_id)
        resp = await self._request("DELETE", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to delete temp password %s: %s", password_id, resp.get("msg"))
            return False

        return True

    async def async_freeze_temp_password(self, device_id: str, password_id: str) -> bool:
        """Freeze a temporary password (Zigbee locks only)."""
        path = FREEZE_PASSWORD_ENDPOINT.format(device_id=device_id, password_id=password_id)
        resp = await self._request("PUT", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to freeze temp password %s: %s", password_id, resp.get("msg"))
            return False

        return True

    async def async_unfreeze_temp_password(self, device_id: str, password_id: str) -> bool:
        """Unfreeze a temporary password (Zigbee locks only)."""
        path = UNFREEZE_PASSWORD_ENDPOINT.format(device_id=device_id, password_id=password_id)
        resp = await self._request("PUT", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to unfreeze temp password %s: %s", password_id, resp.get("msg"))
            return False

        return True
