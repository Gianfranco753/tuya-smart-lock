"""Pulsar real-time connection status binary sensor for Tuya Smart Lock."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory

from ..pulsar import TuyaOpenPulsar


class TuyaPulsarConnection(BinarySensorEntity):
    """Shows whether the Pulsar WebSocket is currently connected.

    Updates instantly when the connection opens or closes — no polling needed.
    Useful for automations that should warn when real-time events are not
    flowing (e.g. after a prolonged network outage).
    """

    _attr_has_entity_name = True
    _attr_name = "Real-time connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, pulsar: TuyaOpenPulsar, device_id: str, device_name: str) -> None:
        self._pulsar = pulsar
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"tuya_smart_lock_{device_id}_pulsar_connection"

    @property
    def device_info(self):
        return {
            "identifiers": {("tuya", self._device_id)},
            "name": self._device_name,
            "manufacturer": "Tuya",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._pulsar.add_state_listener(self._on_connection_change)
        )

    @callback
    def _on_connection_change(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._pulsar.connected
