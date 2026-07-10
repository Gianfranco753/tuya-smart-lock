"""Lock/unlock control and remote-unlock capability check."""

import logging

from ..const import DOOR_OPERATE_ENDPOINT, REMOTE_UNLOCKS_ENDPOINT, TICKET_ENDPOINT

_LOGGER = logging.getLogger(__name__)


class LockControlMixin:
    """Adds lock/unlock and remote-unlock checking to TuyaCloudApi."""

    async def async_check_remote_unlock(self, device_id: str) -> bool:
        """Check if remote unlock without password is enabled."""
        path = REMOTE_UNLOCKS_ENDPOINT.format(device_id=device_id)
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.warning("Could not check remote unlock status: %s", resp.get("msg"))
            return True  # Assume enabled if we can't check

        for unlock_type in resp.get("result", []):
            if unlock_type.get("remote_unlock_type") == "remoteUnlockWithoutPwd":
                return unlock_type.get("open", False)

        return False

    async def async_unlock(self, device_id: str) -> bool:
        """Unlock the door via ticket flow."""
        path = TICKET_ENDPOINT.format(device_id=device_id)
        ticket_resp = await self._request("POST", path)

        if not ticket_resp.get("success"):
            _LOGGER.error("Failed to get ticket: %s", ticket_resp.get("msg"))
            return False

        ticket_id = ticket_resp["result"]["ticket_id"]

        path = DOOR_OPERATE_ENDPOINT.format(device_id=device_id)
        unlock_resp = await self._request("POST", path, {"ticket_id": ticket_id, "open": True})

        if not unlock_resp.get("success"):
            _LOGGER.error("Failed to unlock: %s", unlock_resp.get("msg"))
            return False

        _LOGGER.info("Door %s unlocked successfully", device_id)
        return True

    async def async_lock(self, device_id: str) -> bool:
        """Lock the door via ticket flow."""
        path = TICKET_ENDPOINT.format(device_id=device_id)
        ticket_resp = await self._request("POST", path)

        if not ticket_resp.get("success"):
            _LOGGER.error("Failed to get ticket: %s", ticket_resp.get("msg"))
            return False

        ticket_id = ticket_resp["result"]["ticket_id"]

        path = DOOR_OPERATE_ENDPOINT.format(device_id=device_id)
        lock_resp = await self._request("POST", path, {"ticket_id": ticket_id, "open": False})

        if not lock_resp.get("success"):
            _LOGGER.error("Failed to lock: %s", lock_resp.get("msg"))
            return False

        _LOGGER.info("Door %s locked successfully", device_id)
        return True