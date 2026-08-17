"""MQTT client for Tuya's real-time device message service."""

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
MqConfigFetcher = Callable[[], Awaitable[dict]]


def _decrypt_payload(data: str, pv: str, access_secret: str) -> str:
    """Decrypt a Tuya MQTT message data field.

    pv="2.0" uses AES-GCM with the first 16 bytes of access_secret as key.
    pv="1.0" (and unversioned) uses AES-ECB with a key derived from
    md5(access_secret)[8:24].
    """
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
    """MQTT client for Tuya's real-time device message service.

    Fetches connection credentials from the Tuya REST API before each
    connection attempt — Tuya rotates the password server-side, so
    re-fetching on every reconnect handles expiry automatically.

    Registered handlers receive fully-decrypted device message dicts:

      {
        "devId": "abc123",
        "bizCode": "statusReport",
        "bizData": {"status": [{"code": "door_contact_status", "value": "open"}]},
      }
    """

    def __init__(
        self,
        access_id: str,
        access_secret: str,
        region: str,
        config_fetcher: MqConfigFetcher,
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
        """Register a callback fired on every connection state change.

        Returns a remove callable suitable for passing to async_on_remove.
        """
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
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning(
                    "Tuya MQTT disconnected (%s), reconnecting in %ds",
                    type(err).__name__,
                    delay,
                )
                _LOGGER.debug("MQTT connection error detail:", exc_info=True)
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
        source_topic = config.get("source_topic", {})

        if not url or not username or not password:
            raise RuntimeError(f"Incomplete MQ config from Tuya API: {list(config.keys())}")

        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        port = parsed.port or 8883
        if parsed.scheme in ("mqtts", "ssl"):
            if self._hass:
                tls_context = await self._hass.async_add_executor_job(ssl.create_default_context)
            else:
                loop = asyncio.get_event_loop()
                tls_context = await loop.run_in_executor(None, ssl.create_default_context)
        else:
            tls_context = None

        topics = list(source_topic.values()) if isinstance(source_topic, dict) else [source_topic]
        if not topics:
            topics = [f"{self._access_id}/out/event"]

        _LOGGER.debug("Connecting to Tuya MQTT at %s:%s", hostname, port)
        async with aiomqtt.Client(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            identifier=client_id,
            tls_context=tls_context,
            timeout=30,
        ) as client:
            for topic in topics:
                await client.subscribe(topic)
                _LOGGER.debug("Subscribed to MQTT topic: %s", topic)

            _LOGGER.info("Tuya MQTT connected")
            self._connected = True
            self._notify_state_change()
            try:
                async for message in client.messages:
                    await self._process_message(bytes(message.payload))
            finally:
                self._connected = False
                self._notify_state_change()

    async def _process_message(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
            _LOGGER.debug("Tuya MQTT raw message: %.300s", payload)

            biz_data = msg.get("bizData")

            # Some message formats encrypt the entire inner message under a
            # top-level "data" field rather than inside bizData.
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
            _LOGGER.exception("Failed to process Tuya MQTT message: %.200s", payload[:200])
            return

        try:
            for handler in self._handlers:
                await handler({**msg, "bizData": biz_data})
        except Exception:
            _LOGGER.exception("Tuya MQTT message handler raised an exception")
