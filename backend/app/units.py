"""Units of measure, so each client reads numbers in the units they work in.

US operators think in barrels, feet and psi; most of Latin America uses cubic
metres, metres and kPa. Event attributes declare their unit, values are stored
as received, and conversion happens only for display.
"""

from app.enums import UnitSystem

# unit -> (dimension, factor to the SI base unit, offset)  value_si = value * factor + offset
_UNITS: dict[str, tuple[str, float, float]] = {
    "m": ("length", 1.0, 0.0),
    "ft": ("length", 0.3048, 0.0),
    "km": ("length", 1000.0, 0.0),
    "mi": ("length", 1609.344, 0.0),
    "m3": ("volume", 1.0, 0.0),
    "bbl": ("volume", 0.158987294928, 0.0),
    "l": ("volume", 0.001, 0.0),
    "gal": ("volume", 0.003785411784, 0.0),
    "kpa": ("pressure", 1000.0, 0.0),
    "psi": ("pressure", 6894.757293168, 0.0),
    "bar": ("pressure", 100_000.0, 0.0),
    "c": ("temperature", 1.0, 273.15),
    "f": ("temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
    "kg": ("mass", 1.0, 0.0),
    "lb": ("mass", 0.45359237, 0.0),
    "t": ("mass", 1000.0, 0.0),
    "kmh": ("speed", 1 / 3.6, 0.0),
    "mph": ("speed", 0.44704, 0.0),
    "kn": ("speed", 0.514444444, 0.0),
    "ms": ("speed", 1.0, 0.0),
    # Dimensionless or already universal: never converted.
    "ppm": ("concentration", 1.0, 0.0),
    "pct": ("ratio", 1.0, 0.0),
    "min": ("time", 60.0, 0.0),
    "h": ("time", 3600.0, 0.0),
    "teu": ("count", 1.0, 0.0),
}

_PREFERRED: dict[UnitSystem, dict[str, str]] = {
    UnitSystem.IMPERIAL: {
        "length": "ft",
        "volume": "bbl",
        "pressure": "psi",
        "temperature": "f",
        "mass": "lb",
        "speed": "mph",
    },
    UnitSystem.METRIC: {
        "length": "m",
        "volume": "m3",
        "pressure": "kpa",
        "temperature": "c",
        "mass": "kg",
        "speed": "kmh",
    },
}

# Maritime speed is reported in knots everywhere.
_KEEP_AS_IS = {"kn", "ppm", "pct", "min", "h", "teu", "km", "mi"}


def known_units() -> list[str]:
    return sorted(_UNITS)


def is_known_unit(unit: str) -> bool:
    return unit in _UNITS


def convert(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit == to_unit:
        return value
    try:
        dim_a, factor_a, offset_a = _UNITS[from_unit]
        dim_b, factor_b, offset_b = _UNITS[to_unit]
    except KeyError as exc:
        raise ValueError(f"unknown unit {exc.args[0]!r}") from None
    if dim_a != dim_b:
        raise ValueError(f"cannot convert {from_unit} ({dim_a}) to {to_unit} ({dim_b})")
    si = value * factor_a + offset_a
    return (si - offset_b) / factor_b


def for_display(value: float, unit: str, system: UnitSystem) -> tuple[float, str]:
    """Convert to the client's preferred unit for that dimension, if there is one."""
    if unit not in _UNITS or unit in _KEEP_AS_IS:
        return value, unit
    dimension = _UNITS[unit][0]
    target = _PREFERRED[system].get(dimension, unit)
    return convert(value, unit, target), target


_SWAP_SEPARATORS = str.maketrans({",": ".", ".": ","})


def format_number(value: float, locale: str | None = None) -> str:
    """Two decimals for ordinary readings, three significant digits for tiny ones (so
    0.004 ppm is not shown as 0), with the reader's separators: 1,234.5 in English,
    1.234,5 in Spanish and Portuguese."""
    if value != 0 and abs(value) < 1:
        text = f"{value:.3g}"
        if "e" in text:
            text = f"{value:.6f}".rstrip("0").rstrip(".")
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    if str(locale or "en").startswith(("es", "pt")):
        text = text.translate(_SWAP_SEPARATORS)
    return text


def format_quantity(value: float, unit: str, system: UnitSystem, locale: str | None = None) -> str:
    shown, shown_unit = for_display(value, unit, system)
    return f"{format_number(shown, locale)} {shown_unit}"
