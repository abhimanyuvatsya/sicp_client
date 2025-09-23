"""Shared LED preset definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class LedPreset:
    identifier: str
    label: str
    red: int
    green: int
    blue: int

    @property
    def hex_value(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


_PRESETS: List[LedPreset] = [
    LedPreset("white", "White", 255, 255, 255),
    LedPreset("red", "Red", 255, 0, 0),
    LedPreset("green", "Green", 0, 255, 0),
    LedPreset("blue", "Blue", 0, 0, 255),
    LedPreset("cyan", "Cyan", 0, 255, 255),
    LedPreset("magenta", "Magenta", 255, 0, 255),
    LedPreset("yellow", "Yellow", 255, 255, 0),
    LedPreset("off", "Off", 0, 0, 0),
]

_PRESET_LOOKUP: Dict[str, LedPreset] = {preset.identifier: preset for preset in _PRESETS}
_LABEL_LOOKUP: Dict[str, LedPreset] = {preset.label: preset for preset in _PRESETS}


def presets() -> Iterable[LedPreset]:
    return list(_PRESETS)


def resolve(identifier: str) -> LedPreset:
    try:
        return _PRESET_LOOKUP[identifier]
    except KeyError as exc:
        raise ValueError(f"Unknown LED preset: {identifier}") from exc


def match_rgb(red: int, green: int, blue: int) -> Optional[str]:
    for preset in _PRESETS:
        if preset.red == red and preset.green == green and preset.blue == blue:
            return preset.identifier
    return None


def resolve_label(label: str) -> LedPreset:
    try:
        return _LABEL_LOOKUP[label]
    except KeyError as exc:
        raise ValueError(f"Unknown LED preset label: {label}") from exc


def labels() -> List[str]:
    return [preset.label for preset in _PRESETS]
