from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer, ReceiveEvent

from app.config import settings


class BaseConsumer(AsyncJsonWebsocketConsumer[ReceiveEvent]):
    """Shared consumer defaults — new consumers inherit app-wide config from here."""

    channel_layer_alias = "agent"
    send_completion = settings.send_completion
