# Switch between implementations by changing this import:
#   pulsar_ws   — Pulsar WebSocket (mqe.tuyaXX.com:8285) — currently 401
#   pulsar_mqtt — MQTT-over-WebSocket (m1.tuyaXX.com:443/mqtt) — connects but silent
from .pulsar_mqtt import TuyaOpenPulsar as TuyaOpenPulsar  # noqa: F401
