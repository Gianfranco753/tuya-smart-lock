"""Alarm records history sensor for Tuya Smart Lock."""

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)


class TuyaLockAlarmRecords(CoordinatorEntity, SensorEntity):
    """Sensor exposing recent alarm/security records from the lock.

    The state is the count of records in the latest batch. The full list
    is available as the 'records' extra state attribute, giving automations
    access to timestamps and alarm types for records that occurred while
    HA was offline (unlike the live alarm event entity which only fires
    when the integration is running).
    """

    _attr_has_entity_name = True
    _attr_name = "Alarm records"
    _attr_icon = "mdi:shield-alert-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id: str, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_alarm_records"
        self._device_name = device_name

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    @property
    def native_value(self):
        """Return the number of alarm records in the latest batch."""
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self):
        records = self.coordinator.data or []
        return {
            "records": [
                {
                    "alarm_type": _extract_alarm_type(r),
                    "user_name": r.get("user_name"),
                    "create_time": r.get("create_time"),
                }
                for r in records
            ]
        }


def _extract_alarm_type(record: dict) -> str | None:
    """Pull the alarm DP code from a record's dps list."""
    dps = record.get("dps") or [{}]
    return next(iter(dps[0]), None)
