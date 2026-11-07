from __future__ import annotations

from importlib.metadata import entry_points

from .base import Connector

_REGISTRY: dict[str, type[Connector]] = {}
_LOADED = False


def register(connector: type[Connector]) -> type[Connector]:
    """Register a connector class. Usable as a decorator."""
    if not connector.type:
        raise ValueError("Connector.type must be set")
    _REGISTRY[connector.type] = connector
    return connector


def _load_entry_points() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        eps = entry_points(group="meridian.connectors")
    except TypeError:  # pragma: no cover - older importlib API
        eps = entry_points().get("meridian.connectors", [])  # type: ignore[assignment]
    for ep in eps:
        try:
            connector = ep.load()
            register(connector)
        except Exception:
            import logging

            logging.getLogger("meridian.connectors").exception(
                "connector_plugin_load_failed", extra={"entry_point": ep.name}
            )


def available_connectors() -> dict[str, type[Connector]]:
    _load_entry_points()
    return dict(sorted(_REGISTRY.items()))


def get_connector(connector_type: str) -> Connector:
    _load_entry_points()
    try:
        return _REGISTRY[connector_type]()
    except KeyError as exc:
        raise KeyError(f"Unknown connector type: {connector_type}") from exc
