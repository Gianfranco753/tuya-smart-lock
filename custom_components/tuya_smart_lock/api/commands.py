"""Mixin for sending standard device commands to the Tuya IoT Core API."""

from ..const import DEVICE_COMMAND_ENDPOINT


class CommandsMixin:
    """Sends arbitrary DP commands to a device via the IoT Core command endpoint.

    Used for DPs that don't go through the ticket-based lock flow — e.g.
    toggling normal_open_switch.
    """

    async def async_send_command(self, device_id: str, code: str, value) -> bool:
        path = DEVICE_COMMAND_ENDPOINT.format(device_id=device_id)
        resp = await self._request(
            "POST", path, body={"commands": [{"code": code, "value": value}]}
        )
        return bool(resp.get("success", False))
