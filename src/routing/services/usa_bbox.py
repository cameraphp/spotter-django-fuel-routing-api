from __future__ import annotations

from decimal import Decimal

USA_REGIONS: list[tuple[tuple[float, float], tuple[float, float]]] = [
    ((24.396, 49.384), (-125.0, -66.935)),
    ((51.0, 71.39), (-168.0, -141.0)),
    ((18.9, 22.3), (-160.3, -154.8)),
]


def is_usa_heuristic(latitude: Decimal | float, longitude: Decimal | float) -> bool:
    lat = float(latitude)
    lon = float(longitude)
    for (lat_min, lat_max), (lon_min, lon_max) in USA_REGIONS:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return True
    return False
