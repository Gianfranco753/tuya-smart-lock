"""MQTT-over-WebSocket implementation for Tuya real-time device events.

Fetches credentials from the Tuya access-config API, then connects to
wss://m1.tuyaXX.com:443/mqtt using MQTT protocol over WebSocket.

STATUS: Connected and subscribed, but no device events arrive.
The MQTT source_topic appears to not receive device status updates —
those seem to route exclusively through the Pulsar queue.
"""

import asyncio
import base64
import hashlib
import json
import logging
import ssl
import urllib.parse
from collections.abc import Awaitable, Callable

import aiomqtt
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

_LOGGER = logging.getLogger(__name__)

_INITIAL_RECONNECT_DELAY = 5
_MAX_RECONNECT_DELAY = 300

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
        config_fetcher: Callable[[], Awaitable[dict]],
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
            except Exception as err:
                _LOGGER.warning(
                    "Tuya MQTT disconnected (%s), reconnecting in %ds",
                    type(err).__name__, delay,
                )
                _LOGGER.debug("MQTT error:", exc_info=True)

            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)
            if delay >= _MAX_RECONNECT_DELAY and not self._max_backoff_fired:
                self._max_backoff_fired = True
                if self._on_max_backoff:
                    self._on_max_backoff()

    async def _run_session(self) -> None:
        config = await self._config_fetcher()

        url = config.get("url", "")
        username = config.get("username", "")
        password = config.get("password", "")
        client_id = config.get("client_id", "")

        source_topic_cfg = config.get("source_topic", {})
        topic = source_topic_cfg.get("device", "") if isinstance(source_topic_cfg, dict) else str(source_topic_cfg)

        # url is either ssl://host:port (native MQTT+TLS) or wss://host:port/path (WebSocket)
        is_websocket = url.startswith("wss://")
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if is_websocket else 8883)
        ws_path = parsed.path or "/mqtt"

        _LOGGER.info(
            "MQTT connecting: host=%s port=%d transport=%s username=%s topic=%s",
            host, port, "websocket" if is_websocket else "tcp", username, topic,
        )

        if self._hass:
            tls_ctx = await self._hass.async_add_executor_job(ssl.create_default_context)
        else:
            tls_ctx = ssl.create_default_context()

        client_kwargs = dict(
            hostname=host,
            port=port,
            username=username,
            password=password,
            identifier=client_id,
            tls_context=tls_ctx,
            timeout=30,
        )
        if is_websocket:
            client_kwargs["transport"] = "websockets"
            client_kwargs["websocket_path"] = ws_path

        async with aiomqtt.Client(**client_kwargs) as client:
            _LOGGER.info("MQTT-WS connected; subscribing to %s", topic)
            self._connected = True
            self._notify_state_change()
            try:
                await client.subscribe(topic)
                async for message in client.messages:
                    await self._handle_message(bytes(message.payload))
            finally:
                self._connected = False
                self._notify_state_change()

    async def _handle_message(self, payload: bytes) -> None:
        _LOGGER.debug("MQTT-WS raw message: %.500s", payload[:500])
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
            _LOGGER.exception("Failed to process MQTT message: %.200s", payload[:200])
            return

        _LOGGER.debug("MQTT-WS decoded: %s", {**msg, "bizData": biz_data})

        try:
            for handler in self._handlers:
                await handler({**msg, "bizData": biz_data})
        except Exception:
            _LOGGER.exception("MQTT message handler raised")
