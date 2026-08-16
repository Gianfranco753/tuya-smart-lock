"""Event entities for Tuya Smart Lock: unlock history and alarms."""

import logging

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN, SIGNAL_LOCK_ALARM

_LOGGER = logging.getLogger(__name__)

UNLOCK_METHOD_EVENT_TYPES = {
    "unlock_fingerprint": "fingerprint",
    "unlock_password": "password",
    "unlock_temporary": "temporary_password",
    "unlock_dynamic": "dynamic_password",
    "unlock_card": "card",
    "unlock_face": "face",
    "unlock_app": "app",
    "unlock_remote": "remote",
    "lock_gesture": "gesture",
    "single_use_password": "single_use_password",
}

ALARM_EVENT_TYPES = [
    "wrong_fingerprint",
    "wrong_password",
    "wrong_card",
    "wrong_face",
    "hijack",
    "low_battery",
    "door_open_timeout",
    "other",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up unlock history and alarm event entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    entry_data = data["entry_data"]
    records_coordinator = data["records_coordinator"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    async_add_entities([
        TuyaLockUnlockEvent(records_coordinator, device_id, device_name),
        TuyaLockAlarmEvent(device_id, device_name),
    ])


class TuyaLockUnlockEvent(CoordinatorEntity, EventEntity):
    """Fires a Home Assistant event each time a new unlock record appears.

    Driven by records_coordinator. The Pulsar handler triggers an immediate
    records refresh on any unlock DP, so events arrive within one API
    round-trip of the physical unlock instead of waiting up to 2 minutes.
    """

    _attr_has_entity_name = True
    _attr_name = "Unlock history"
    _attr_icon = "mdi:history"
    _attr_event_types = [*UNLOCK_METHOD_EVENT_TYPES.values(), "other"]

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_unlock_history"
        self._device_name = device_name
        self._last_seen_record_id: str | None = None
        self._baseline_initialized = False

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def _newest_record(self) -> dict | None:
        records = self.coordinator.data or []
        return records[0] if records else None

    def _handle_coordinator_update(self) -> None:
        record = self._newest_record
        if record is None:
            return

        record_id = record.get("record_id")

        if not self._baseline_initialized:
            self._last_seen_record_id = record_id
            self._baseline_initialized = True
            self.async_write_ha_state()
            return

        if record_id is not None and record_id != self._last_seen_record_id:
            self._last_seen_record_id = record_id

            dps = record.get("dps") or [{}]
            dp_code = next(iter(dps[0]), None)
            event_type = UNLOCK_METHOD_EVENT_TYPES.get(dp_code, "other")

            self._trigger_event(
                event_type,
                {
                    "unlock_name": record.get("unlock_name"),
                    "user_name": record.get("user_name"),
                    "record_type": record.get("record_type"),
                },
            )

        self.async_write_ha_state()


class TuyaLockAlarmEvent(EventEntity):
    """Fires a Home Assistant event each time the lock reports an alarm.

    Uses a dispatcher signal (sent by the Pulsar handler in __init__.py)
    instead of a coordinator so repeated identical alarm codes — e.g. three
    consecutive wrong-password attempts — each fire a separate event even
    though the DP value doesn't change between them.
    """

    _attr_has_entity_name = True
    _attr_name = "Alarm"
    _attr_icon = "mdi:alarm-light"
    _attr_should_poll = False
    _attr_event_types = ALARM_EVENT_TYPES

    def __init__(self, device_id: str, device_name: str) -> None:
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_alarm"

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LOCK_ALARM.format(self._device_id),
                self._handle_alarm,
            )
        )

    @callback
    def _handle_alarm(self, alarm_code: str) -> None:
        known = set(ALARM_EVENT_TYPES) - {"other"}
        event_type = alarm_code if alarm_code in known else "other"
        self._trigger_event(event_type, {"alarm_code": alarm_code})
        self.async_write_ha_state()
