"""Typed reading of user settings, falling back to the default on missing or broken values."""

from PySide6.QtCore import QSettings


def open_settings() -> QSettings:
    """The editor's settings in an INI file, so they look the same on every platform."""
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "lay6-editor", "editor")


def read_float(settings: QSettings, key: str, default: float) -> float:
    try:
        return float(str(settings.value(key, default)))
    except ValueError:
        return default


def read_int(settings: QSettings, key: str, default: int) -> int:
    try:
        return int(str(settings.value(key, default)))
    except ValueError:
        return default


def read_bool(settings: QSettings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return default


def read_str(settings: QSettings, key: str, default: str = "") -> str:
    value = settings.value(key, default)
    return default if value is None else str(value)
