import os
from typing import Any


_DISABLED_SECONDS_VALUES = {"", "0", "false", "no", "off", "none", "null"}


def aliyun_realtime_ws_connect_kwargs(*, max_size: int = 2**22) -> dict[str, Any]:
    """Common options for long-lived DashScope realtime WebSocket clients."""
    ping_interval = _optional_seconds("ALIYUN_WS_PING_INTERVAL_SECONDS", default=0.0)
    ping_timeout = _optional_seconds("ALIYUN_WS_PING_TIMEOUT_SECONDS", default=30.0)
    return {
        "max_size": max_size,
        "ping_interval": ping_interval,
        "ping_timeout": ping_timeout if ping_interval is not None else None,
    }


def _optional_seconds(env_name: str, *, default: float) -> float | None:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        value = default
    else:
        normalized = raw_value.strip().lower()
        if normalized in _DISABLED_SECONDS_VALUES:
            return None
        try:
            value = float(normalized)
        except ValueError:
            value = default

    if value <= 0:
        return None
    return max(value, 1.0)
