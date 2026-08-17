"""Pulsar WebSocket implementation for Tuya real-time device events.

Connects directly to mqe.tuyaXX.com:8285 using the Pulsar WebSocket protocol.
Credentials: username=access_id, password from config_fetcher (server-computed).

STATUS: Returns HTTP 401. md5(access_id+access_secret) does not authenticate.
Testing with server-computed password from access-config API instead.
"""

import asyncio
import base64
import hashlib
import json
import logging
import urllib.parse
from collections.abc import Awaitable, Callable

import aiohttp
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

_LOGGER = logging.getLogger(__name__)

_INITIAL_RECONNECT_DELAY = 5
_MAX_RECONNECT_DELAY = 300

_PULSAR_HOSTS = {
    "eu": "mqe.tuyaeu.com",
    "us": "mqe.tuyaus.com",
    "cn": "mqe.tuyacn.com",
    "in": "mqe.tuyain.com",
}

MessageHandler = Callable[[dict], Awaitable[None]]
SimpleCallback = Callable[[], None]


def _decrypt_payload(data: str, pv: str, access_secret: str) -> str:
    raw = base64.b64decode(data)

    if pv == "2.0":
        key = access_secret[:16].encode()
        nonce, tag, ciphertext = raw[:12], raw[-16:], raw[12:-16]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode()

    ecb_key = hashlib.md5(access_secret.encode()).hexdigest()[8:24].encode()
    cipher = AES.new(ecb_key, AES.MODE_ECB)
    return unpad(cipher.decrypt(raw), AES.block_size).decode()


class TuyaOpenPulsar:
    def __init__(
        self,
        access_id: str,
        access_secret: str,
        region: str,
        config_fetcher: Callable[[], Awaitable[dict]] | None = None,
        hass=None,
        on_max_backoff: SimpleCallback | None = None,
        on_reconnect: SimpleCallback | None = None,
    ) -> None:
        self._access_id = access_id
        self._access_secret = access_secret
        self._region = region
        self._config_fetcher = config_fetcher
        self._hass = hass
        self._handlers: list[MessageHandler] = []
        self._task: asyncio.Task | None = None
        self._on_max_backoff = on_max_backoff
        self._on_reconnect = on_reconnect
        self._max_backoff_fired = False
        self._connected = False
        self._state_listeners: list[SimpleCallback] = []

    @property
    def connected(self) -> bool:
        return self._connected

    def add_state_listener(self, listener: SimpleCallback) -> SimpleCallback:
        self._state_listeners.append(listener)

        def _remove() -> None:
            try:
                self._state_listeners.remove(listener)
            except ValueError:
                pass

        return _remove

    def _notify_state_change(self) -> None:
        for listener in self._state_listeners:
            listener()

    def add_message_handler(self, handler: MessageHandler) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._connect_with_backoff())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _connect_with_backoff(self) -> None:
        delay = _INITIAL_RECONNECT_DELAY
        while True:
            try:
                await self._run_session()
                delay = _INITIAL_RECONNECT_DELAY
                if self._max_backoff_fired:
                    self._max_backoff_fired = False
                    if self._on_reconnect:
                        self._on_reconnect()
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as err:
                _LOGGER.warning(
                    "Pulsar-WS handshake failed (HTTP %s), reconnecting in %ds",
                    err.status, delay,
                )
                _LOGGER.debug("Pulsar handshake headers: %s", dict(err.headers or {}))
            except Exception as err:
                _LOGGER.warning(
                    "Pulsar-WS disconnected (%s), reconnecting in %ds",
                    type(err).__name__, delay,
                )
                _LOGGER.debug("Pulsar error:", exc_info=True)

            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)
            if delay >= _MAX_RECONNECT_DELAY and not self._max_backoff_fired:
                self._max_backoff_fired = True
                if self._on_max_backoff:
                    self._on_max_backoff()

    async def _get_password(self) -> str:
        """Return the Pulsar auth password.

        Tries the server-computed password from access-config first (if a
        config_fetcher is wired up), falling back to the md5 formula used
        by Tuya's own Python SDKs.
        """
        if self._config_fetcher:
            try:
                config = await self._config_fetcher()
                password = config.get("password", "")
                if password:
                    _LOGGER.debug("Using server-computed password from access-config")
                    return password
            except Exception:
                _LOGGER.debug("access-config failed, falling back to md5 formula", exc_info=True)

        password = hashlib.md5(f"{self._access_id}{self._access_secret}".encode()).hexdigest()
        _LOGGER.debug("Using md5(access_id+access_secret) password formula")
        return password

    async def _run_session(self) -> None:
        host = _PULSAR_HOSTS.get(self._region, "mqe.tuyaus.com")
        subscription = f"{self._access_id}-sub"
        path = f"/ws/v2/consumer/persistent/{self._access_id}/out/event/{subscription}"

        password = await self._get_password()

        qs = urllib.parse.urlencode({
            "subscriptionType": "Failover",
            "ackTimeoutMillis": "30000",
            "username": self._access_id,
            "password": password,
        })
        url = f"wss://{host}:8285{path}?{qs}"

        _LOGGER.info(
            "Pulsar-WS connecting: %s:8285%s (subscription=%s)",
            host, path, subscription,
        )

        if self._hass:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(self._hass)
            own_session = False
        else:
            session = aiohttp.ClientSession()
            own_session = True

        try:
            async with session.ws_connect(url, heartbeat=30) as ws:
                _LOGGER.info("Pulsar-WS connected")
                self._connected = True
                self._notify_state_change()
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(ws, msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            _LOGGER.debug("Pulsar-WS closed (type=%s)", msg.type)
                            break
                finally:
                    self._connected = False
                    self._notify_state_change()
        finally:
            if own_session:
                await session.close()

    async def _handle_message(self, ws: aiohttp.ClientWebSocketResponse, text: str) -> None:
        message_id = None
        try:
            envelope = json.loads(text)
            message_id = envelope.get("messageId")
            payload = base64.b64decode(envelope.get("payload", ""))
            _LOGGER.debug("Pulsar-WS message (id=%s): %.500s", message_id, payload[:500])
            await self._process_message(payload)
        except Exception:
            _LOGGER.exception("Failed to handle Pulsar message: %.200s", text[:200])

        if message_id:
            await ws.send_str(json.dumps({"messageId": message_id}))

    async def _process_message(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
            biz_data = msg.get("bizData")

            if biz_data is None and "data" in msg:
                pv = str(msg.get("pv", "1.0"))
                msg = json.loads(_decrypt_payload(msg["data"], pv, self._access_secret))
                biz_data = msg.get("bizData")

            if isinstance(biz_data, str):
                biz_data = json.loads(_decrypt_payload(biz_data, "1.0", self._access_secret))
            elif isinstance(biz_data, dict) and "data" in biz_data:
                pv = str(biz_data.get("pv", "1.0"))
                biz_data = json.loads(_decrypt_payload(biz_data["data"], pv, self._access_secret))

        except Exception:
            _LOGGER.exception("Failed to process Pulsar message: %.200s", payload[:200])
            return

        _LOGGER.debug("Pulsar-WS decoded: %s", {**msg, "bizData": biz_data})

        try:
            for handler in self._handlers:
                await handler({**msg, "bizData": biz_data})
        except Exception:
            _LOGGER.exception("Pulsar message handler raised")
