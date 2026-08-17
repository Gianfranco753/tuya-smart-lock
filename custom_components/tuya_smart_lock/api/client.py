"""Low-level HTTP client for the Tuya Cloud API: auth, signing, requests."""

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import API_REGIONS

_LOGGER = logging.getLogger(__name__)


class TuyaApiError(Exception):
    """Raised when a Tuya API request fails at the network level."""


class TuyaApiClient:
    """Handles token lifecycle, request signing, and raw HTTP calls.

    Subclassed (via mixins) by TuyaCloudApi, which adds the actual
    lock/password/status/records endpoints. This class only knows how
    to authenticate and sign requests — it has no knowledge of what a
    "lock" or a "password" is.
    """

    def __init__(self, access_id: str, access_secret: str, region: str = "eu", hass=None) -> None:
        self._access_id = access_id
        self._access_secret = access_secret
        self._base_url = f"https://{API_REGIONS[region]}"
        self._hass = hass
        self._token: str | None = None
        self._token_expiry: float = 0
        self._uid: str | None = None
        # Stable identifier for this account's Pulsar subscription.
        # Derived from access_id so it's the same across HA restarts — Tuya
        # uses it to resume the same consumer and deliver buffered messages.
        self._link_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, access_id))
        # Prevents two concurrent callers from both refreshing an expired token.
        self._token_lock = asyncio.Lock()

    async def _ensure_token(self) -> None:
        """Get or refresh the access token."""
        async with self._token_lock:
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

            session = async_get_clientsession(self._hass) if self._hass else aiohttp.ClientSession()
            try:
                cm = session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10))
                async with cm as resp:
                    data = await resp.json()
            except aiohttp.ClientError as err:
                _LOGGER.error("Network error getting Tuya token: %s", err)
                raise TuyaApiError(f"Cannot reach Tuya Cloud API: {err}") from err
            except TimeoutError as err:
                _LOGGER.error("Timeout getting Tuya token")
                raise TuyaApiError("Timeout connecting to Tuya Cloud API") from err
            except json.JSONDecodeError as err:
                _LOGGER.error("Invalid JSON in Tuya token response")
                raise TuyaApiError("Tuya Cloud API returned invalid JSON for token") from err
            finally:
                if not self._hass:
                    await session.close()

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

    async def async_get_mq_config(self) -> dict:
        """Fetch the Pulsar message-queue connection config from Tuya's API.

        Returns the `result` dict which contains: url, username, password,
        client_id, expire_time, source_topic, sink_topic.
        The password is computed server-side and must be used as-is — do not
        try to derive it locally.
        """
        # _ensure_token must run before we read self._uid, which is populated
        # as a side-effect of the token exchange.
        await self._ensure_token()
        resp = await self._request(
            "POST",
            "/v1.0/iot-03/open-hub/access-config",
            body={
                "uid": self._uid,
                "link_id": self._link_id,
                "link_type": "mqtt",
                "topics": "device.status",
                "msg_encrypted_version": "2.0",
            },
        )
        if not resp.get("success"):
            raise TuyaApiError(f"Failed to get MQ config: {resp.get('msg')}")
        return resp.get("result", {})

    async def _request(
        self, method: str, path: str, body: dict | None = None, params: dict | None = None,
    ) -> dict:
        """Make a signed request to the Tuya API.

        If params is given, it's sorted alphabetically by key before being
        appended to the path — Tuya's signature algorithm requires the
        exact same alphabetically-sorted query string to be used both for
        signing and for the actual request URL, or the server rejects the
        request with "sign invalid".
        """
        await self._ensure_token()

        full_path = path
        if params:
            sorted_query = "&".join(f"{k}={params[k]}" for k in sorted(params))
            full_path = f"{path}?{sorted_query}"

        url = f"{self._base_url}{full_path}"
        body_str = json.dumps(body) if body else ""
        headers = self._sign_request(method, full_path, body_str)

        session = async_get_clientsession(self._hass) if self._hass else aiohttp.ClientSession()
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            cm = session.request(
                method,
                url,
                headers=headers,
                data=body_str if body_str else None,
                timeout=timeout,
            )
            async with cm as resp:
                return await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error calling Tuya API (%s): %s", full_path, err)
            raise TuyaApiError(f"Cannot reach Tuya Cloud API: {err}") from err
        except TimeoutError as err:
            _LOGGER.error("Timeout calling Tuya API (%s)", full_path)
            raise TuyaApiError(f"Timeout connecting to Tuya Cloud API ({full_path})") from err
        except json.JSONDecodeError as err:
            _LOGGER.error("Invalid JSON response from Tuya API (%s)", full_path)
            raise TuyaApiError(f"Tuya API returned invalid JSON ({full_path})") from err
        finally:
            if not self._hass:
                await session.close()
