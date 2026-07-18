from fast_channels.layers import (
    BaseChannelLayer,
    InMemoryChannelLayer,
    has_layers,
    register_channel_layer,
)

from app.config import settings


def setup_layers(force: bool = False) -> None:
    if has_layers() and not force:
        return

    layer: BaseChannelLayer
    if settings.redis_url:
        from fast_channels.layers.redis import RedisPubSubChannelLayer

        layer = RedisPubSubChannelLayer(hosts=[settings.redis_url], prefix="agent")
    else:
        # Single-process default; set REDIS_URL to scale across instances/workers.
        layer = InMemoryChannelLayer()

    register_channel_layer("agent", layer)
