"""Async WebSocket client for Tuya's Pulsar real-time message gateway."""

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable

import aiohttp
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

PULSAR_WS_ENDPOINTS = {
    "eu": "wss://mqe.tuyaeu.com/ws/v2/consumer/persistent",
    "us": "wss://mqe.tuyaus.com/ws/v2/consumer/persistent",
    "cn": "wss://mqe.tuyacn.com/ws/v2/consumer/persistent",
    "in": "wss://mqe.tuyain.com/ws/v2/consumer/persistent",
}

_INITIAL_RECONNECT_DELAY = 5
_MAX_RECONNECT_DELAY = 300
_MAX_HANDLER_RETRIES = 3

MessageHandler = Callable[[dict], Awaitable[None]]
SimpleCallback = Callable[[], None]


def _build_auth_header(access_id: str, access_secret: str) -> str:
    """Derive the Basic auth header Tuya's Pulsar WebSocket gateway expects."""
    md5_secret = hashlib.md5(access_secret.encode()).hexdigest()
    password = hashlib.md5((access_id + md5_secret).encode()).hexdigest()[8:24]
    token = base64.b64encode(f"{access_id}:{password}".encode()).decode()
    return f"Basic {token}"


def _decrypt_payload(data: str, pv: str, access_secret: str) -> str:
    """Decrypt a Tuya Pulsar message data field.

    pv="2.0" uses AES-GCM with the first 16 bytes of access_secret as key.
    pv="1.0" (and unversioned) uses AES-ECB with a key derived from
    md5(access_secret)[8:24] — a separate derivation from the ticket-key
    scheme in crypto.py.
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
    """Async WebSocket client for Tuya's Pulsar message gateway.

    Uses aiohttp (a HA core dependency) so no extra pip packages are needed.
    Registered handlers receive fully-decrypted device message dicts:

      {
        "devId": "abc123",
        "bizCode": "statusReport",
        "bizData": {"status": [{"code": "door_contact_status", "value": "open"}]},
      }

    The connection loop reconnects automatically with exponential backoff on
    any error.
    """

    def __init__(
        self,
        access_id: str,
        access_secret: str,
        region: str,
        hass=None,
        on_max_backoff: SimpleCallback | None = None,
        on_reconnect: SimpleCallback | None = None,
    ) -> None:
        self._access_id = access_id
        self._access_secret = access_secret
        self._region = region
        self._hass = hass
        self._handlers: list[MessageHandler] = []
        self._task: asyncio.Task | None = None
        self._on_max_backoff = on_max_backoff
        self._on_reconnect = on_reconnect
        self._max_backoff_fired = False
        self._handler_failures: dict[str, int] = {}
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

    def _ws_url(self) -> str:
        base = PULSAR_WS_ENDPOINTS[self._region]
        return (
            f"{base}/{self._access_id}/out/event/{self._access_id}-sub"
            "?ackTimeoutMillis=3000&subscriptionType=Failover"
        )

    async def _connect_with_backoff(self) -> None:
        delay = _INITIAL_RECONNECT_DELAY
        while True:
            try:
                await self._run_session()
                # Session ended with a clean CLOSE/ERROR frame — still a disconnect.
                # Reset delay and dismiss any outstanding notification, then sleep
                # before reconnecting to avoid a tight loop on rapid server closes.
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
                    "Pulsar WebSocket disconnected (%s), reconnecting in %ds", err, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, _MAX_RECONNECT_DELAY)
                if delay >= _MAX_RECONNECT_DELAY and not self._max_backoff_fired:
                    self._max_backoff_fired = True
                    if self._on_max_backoff:
                        self._on_max_backoff()

    async def _run_session(self) -> None:
        auth = _build_auth_header(self._access_id, self._access_secret)
        session = async_get_clientsession(self._hass) if self._hass else aiohttp.ClientSession()

        try:
            async with session.ws_connect(
                self._ws_url(),
                headers={"Authorization": auth},
                heartbeat=30,
            ) as ws:
                _LOGGER.info("Tuya Pulsar WebSocket connected")
                self._connected = True
                self._notify_state_change()
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._process_message(ws, msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break
                finally:
                    self._connected = False
                    self._notify_state_change()
        finally:
            if not self._hass:
                await session.close()

    async def _process_message(
        self, ws: aiohttp.ClientWebSocketResponse, raw: str
    ) -> None:
        # Phase 1: parse and decrypt. On failure, ack to stop infinite redelivery
        # of a permanently corrupt message, then bail out early.
        message_id = None
        try:
            envelope = json.loads(raw)
            message_id = envelope.get("messageId")

            payload_b64 = envelope.get("payload")
            if not payload_b64:
                if message_id:
                    await ws.send_str(json.dumps({"messageId": message_id}))
                return

            outer = json.loads(base64.b64decode(payload_b64))
            biz_data = outer.get("bizData")

            if isinstance(biz_data, str):
                # Old protocol: bizData is an AES-ECB encrypted string
                biz_data = json.loads(_decrypt_payload(biz_data, "1.0", self._access_secret))
            elif isinstance(biz_data, dict) and "data" in biz_data:
                # New protocol: bizData = {"pv": "2.0", "t": ..., "data": "<encrypted>"}
                pv = str(biz_data.get("pv", "1.0"))
                biz_data = json.loads(_decrypt_payload(biz_data["data"], pv, self._access_secret))

        except Exception:
            _LOGGER.exception("Failed to process Pulsar message: %.200s", raw)
            if message_id:
                try:
                    await ws.send_str(json.dumps({"messageId": message_id}))
                except Exception:
                    pass  # ws may be closing; losing this ack is acceptable
            return

        # Phase 2: dispatch to handlers. Withhold the ack on failure so Tuya
        # redelivers (at-least-once semantics), but give up after
        # _MAX_HANDLER_RETRIES to avoid an infinite loop when the failure is
        # permanent (e.g. a malformed-but-parseable message from the broker).
        try:
            for handler in self._handlers:
                await handler({**outer, "bizData": biz_data})
        except Exception:
            _LOGGER.exception("Pulsar message handler raised an exception")
            if message_id:
                failures = self._handler_failures.get(message_id, 0) + 1
                if failures >= _MAX_HANDLER_RETRIES:
                    _LOGGER.warning(
                        "Giving up on message %s after %d failures; acking to stop redelivery",
                        message_id,
                        failures,
                    )
                    self._handler_failures.pop(message_id, None)
                    try:
                        await ws.send_str(json.dumps({"messageId": message_id}))
                    except Exception:
                        pass
                else:
                    self._handler_failures[message_id] = failures
            return

        self._handler_failures.pop(message_id, None)
        if message_id:
            await ws.send_str(json.dumps({"messageId": message_id}))
