"""Tuya Cloud API client for Smart Lock operations."""

import hashlib
import hmac
import json
import logging
import time

import aiohttp

from .const import (
    API_REGIONS,
    DOOR_OPERATE_ENDPOINT,
    DYNAMIC_PASSWORD_ENDPOINT,
    FREEZE_PASSWORD_ENDPOINT,
    LOCK_CATEGORIES,
    REMOTE_UNLOCKS_ENDPOINT,
    STATUS_ENDPOINT,
    TEMP_PASSWORD_DELETE_ENDPOINT,
    TEMP_PASSWORDS_LIST_ENDPOINT,
    TICKET_ENDPOINT,
    TEMP_PASSWORD_ENDPOINT,
    UNFREEZE_PASSWORD_ENDPOINT,
)

from .crypto import decrypt_ticket_key, encrypt_password

_LOGGER = logging.getLogger(__name__)


class TuyaApiError(Exception):
    """Raised when a Tuya API request fails at the network level."""


class TuyaCloudApi:
    """Tuya Cloud API client for lock operations."""

    def __init__(self, access_id: str, access_secret: str, region: str = "eu") -> None:
        self._access_id = access_id
        self._access_secret = access_secret
        self._base_url = f"https://{API_REGIONS[region]}"
        self._token: str | None = None
        self._token_expiry: float = 0
        self._uid: str | None = None

    async def _ensure_token(self) -> None:
        """Get or refresh the access token."""
        if self._token and time.time() < self._token_expiry:
            return

        url = f"{self._base_url}/v1.0/token?grant_type=1"
        t = str(int(time.time() * 1000))

        string_to_sign = (
            "GET\n"
            + hashlib.sha256(b"").hexdigest()
            + "\n\n"
            + "/v1.0/token?grant_type=1"
        )
        sign_str = self._access_id + t + string_to_sign
        sign = hmac.new(
            self._access_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest().upper()

        headers = {
            "client_id": self._access_id,
            "sign": sign,
            "t": t,
            "sign_method": "HMAC-SHA256",
            "secret": self._access_secret,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error getting Tuya token: %s", err)
            raise TuyaApiError(f"Cannot reach Tuya Cloud API: {err}") from err
        except TimeoutError as err:
            _LOGGER.error("Timeout getting Tuya token")
            raise TuyaApiError("Timeout connecting to Tuya Cloud API") from err

        if not data.get("success"):
            _LOGGER.error("Failed to get Tuya token: %s", data.get("msg"))
            raise ConnectionError(f"Tuya token error: {data.get('msg')}")

        result = data["result"]
        self._token = result["access_token"]
        self._token_expiry = time.time() + result["expire_time"] - 60
        self._uid = result.get("uid")

    def _sign_request(self, method: str, path: str, body: str = "") -> dict:
        """Build signed headers for a Tuya API request."""
        t = str(int(time.time() * 1000))
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = f"{method}\n{content_hash}\n\n{path}"
        sign_str = self._access_id + self._token + t + string_to_sign
        sign = hmac.new(
            self._access_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest().upper()

        return {
            "client_id": self._access_id,
            "access_token": self._token,
            "sign": sign,
            "t": t,
            "sign_method": "HMAC-SHA256",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        """Make a signed request to the Tuya API."""
        await self._ensure_token()
        url = f"{self._base_url}{path}"
        body_str = json.dumps(body) if body else ""
        headers = self._sign_request(method, path, body_str)

        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    data=body_str if body_str else None,
                    timeout=timeout,
                ) as resp:
                    return await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error calling Tuya API (%s): %s", path, err)
            raise TuyaApiError(f"Cannot reach Tuya Cloud API: {err}") from err
        except TimeoutError as err:
            _LOGGER.error("Timeout calling Tuya API (%s)", path)
            raise TuyaApiError(f"Timeout connecting to Tuya Cloud API ({path})") from err

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

        # Response structure: result.devices (list)
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

    async def async_get_auto_lock_time(self, device_id: str) -> int | None:
        """Get the auto-lock delay in seconds from device status."""
        path = STATUS_ENDPOINT.format(device_id=device_id)
        resp = await self._request("GET", path)

        if not resp.get("success"):
            return None

        for dp in resp.get("result", []):
            if dp["code"] == "auto_lock_time":
                return dp["value"]

        return None

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

    async def async_get_lock_state(self, device_id: str) -> bool | None:
        """Get lock_motor_state. Returns True if unlocked, False if locked, None on error."""
        path = STATUS_ENDPOINT.format(device_id=device_id)
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to get status: %s", resp.get("msg"))
            return None

        for dp in resp.get("result", []):
            if dp["code"] == "lock_motor_state":
                return dp["value"]

        return None

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

    async def async_get_battery_level(self, device_id: str) -> int | None:
        """Get battery percentage from device status."""
        path = STATUS_ENDPOINT.format(device_id=device_id)
        resp = await self._request("GET", path)

        if not resp.get("success"):
            _LOGGER.error("Failed to get battery level: %s", resp.get("msg"))
            return None

        for dp in resp.get("result", []):
            if dp["code"] in ("battery_percentage", "residual_electricity"):
                return dp["value"]

        return None

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
