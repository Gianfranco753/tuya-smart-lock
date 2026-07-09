"""Event entity exposing unlock history for Tuya Smart Lock."""

import logging

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Maps Tuya's unlock DP codes (found in each record's "dps") to short,
# stable event_type strings used by this entity.
UNLOCK_METHOD_EVENT_TYPES = {
    "unlock_fingerprint": "fingerprint",
    "unlock_password": "password",
    "unlock_temporary": "temporary_password",
    "unlock_dynamic": "dynamic_password",
    "unlock_card": "card",
    "unlock_face": "face",
    "unlock_app": "app",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the unlock history event entity."""
    data = hass.data[DOMAIN][entry.entry_id]
    entry_data = data["entry_data"]
    records_coordinator = data["records_coordinator"]
    device_id = entry_data[CONF_DEVICE_ID]
    device_name = entry_data[CONF_DEVICE_NAME]

    async_add_entities([TuyaLockUnlockEvent(records_coordinator, device_id, device_name)])


class TuyaLockUnlockEvent(CoordinatorEntity, EventEntity):
    """Fires a Home Assistant event each time a new unlock record appears.

    Tuya's records API is poll-based (shared 2-min records_coordinator
    interval), so events lag the real unlock by up to that interval.
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
        """Link to the same device as the lock entity."""
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
        """Fire an event when a new unlock record is detected."""
        record = self._newest_record
        if record is None:
            return

        record_id = record.get("record_id")

        if not self._baseline_initialized:
            # First update after startup/reload: remember the current
            # latest record without firing, so we don't replay old
            # history as if it just happened.
            self._last_seen_record_id = record_id
            self._baseline_initialized = True
            self.async_write_ha_state()
            return

        if record_id and record_id != self._last_seen_record_id:
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
