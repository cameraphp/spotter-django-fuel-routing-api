from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

from routing.services.geocoding import GeocodeProvider, GeocodeResult
from routing.services.routing import RouteResult, RoutingProvider

EARTH_RADIUS_MILES = 3958.8


def _haversine_km_to_mi_float_approx_d(a_lat, a_lon, b_lat, b_lon) -> float:
    dlat = math.radians(float(b_lat) - float(a_lat))
    dlon = math.radians(float(b_lon) - float(a_lon))
    la1 = math.radians(float(a_lat))
    la2 = math.radians(float(b_lat))
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2.0 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


class MockGeocoder(GeocodeProvider):
    def __init__(self, mapping: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._mapping: dict[str, dict[str, Any]] = dict(mapping or {})
        self._last_query: str | None = None

    def add(self, query: str, lat: Decimal | float, lon: Decimal | float, country_code: str = 'us', state_code: str | None = None) -> None:
        self._mapping[query.strip().lower()] = {
            'latitude': Decimal(str(lat)),
            'longitude': Decimal(str(lon)),
            'country_code': country_code,
            'state_code': state_code,
            'display_name': query,
        }

    def geocode(self, query: str, country_codes: str | None = 'us') -> GeocodeResult:
        self._last_query = query
        self.external_calls += 1
        key = query.strip().lower()
        entry = self._mapping.get(key)
        if entry is None:
            return GeocodeResult(None, None)
        return GeocodeResult(
            latitude=entry['latitude'],
            longitude=entry['longitude'],
            country_code=entry.get('country_code'),
            state_code=entry.get('state_code'),
            display_name=entry.get('display_name'),
            raw=entry,
        )

    def reverse(self, latitude: Decimal, longitude: Decimal) -> GeocodeResult:
        self.external_calls += 1
        for _, entry in self._mapping.items():
            d = _haversine_km_to_mi_float_approx_d(
                entry['latitude'], entry['longitude'], latitude, longitude
            )
            if d < 3.0:
                return GeocodeResult(
                    latitude=entry['latitude'],
                    longitude=entry['longitude'],
                    country_code=entry.get('country_code'),
                    state_code=entry.get('state_code'),
                    display_name=entry.get('display_name'),
                    raw=entry,
                )
        return GeocodeResult(None, None)


class MockRoutingProvider(RoutingProvider):
    def __init__(
        self,
        routes: dict[tuple[float, float, float, float], dict[str, Any]] | None = None,
        default_distance_miles: Decimal | float | None = None,
        default_n_points: int = 20,
    ) -> None:
        super().__init__()
        self._routes: dict[tuple[float, float, float, float], dict[str, Any]] = {}
        for (a, b, c, d), v in (routes or {}).items():
            self._routes[(round(float(a), 5), round(float(b), 5), round(float(c), 5), round(float(d), 5))] = v
        self._default_distance = None if default_distance_miles is None else Decimal(str(default_distance_miles))
        self._default_n_points = default_n_points

    def add(
        self,
        start_lat, start_lon, end_lat, end_lon,
        distance_miles,
        n_points: int = 20,
        duration_seconds: Decimal | float | None = None,
    ) -> None:
        coords: list[list[float]] = []
        s_lat, s_lon = float(start_lat), float(start_lon)
        e_lat, e_lon = float(end_lat), float(end_lon)
        for i in range(max(2, n_points)):
            t = i / (max(2, n_points) - 1)
            lat = s_lat + (e_lat - s_lat) * t
            lon = s_lon + (e_lon - s_lon) * t
            coords.append([lon, lat])
        key = (round(s_lat, 5), round(s_lon, 5), round(e_lat, 5), round(e_lon, 5))
        self._routes[key] = {
            'distance_miles': Decimal(str(distance_miles)),
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'duration_seconds': (Decimal(str(duration_seconds)) if duration_seconds is not None else None),
        }

    def route(self, start_latitude, start_longitude, end_latitude, end_longitude) -> RouteResult:
        self.external_calls += 1
        key = (round(float(start_latitude), 5), round(float(start_longitude), 5),
               round(float(end_latitude), 5), round(float(end_longitude), 5))
        entry = self._routes.get(key)
        if entry is None and self._default_distance is not None:
            distance_miles = self._default_distance
            coords: list[list[float]] = []
            s_lat = float(start_latitude)
            s_lon = float(start_longitude)
            e_lat = float(end_latitude)
            e_lon = float(end_longitude)
            n = max(2, self._default_n_points)
            for i in range(n):
                t = i / (n - 1)
                lat = s_lat + (e_lat - s_lat) * t
                lon = s_lon + (e_lon - s_lon) * t
                coords.append([lon, lat])
            return RouteResult(
                distance_miles=distance_miles,
                geometry_geojson=json.dumps({'type': 'LineString', 'coordinates': coords}),
                duration_seconds=None,
            )
        if entry is None:
            from routing.services.errors import ProviderError
            raise ProviderError('MockRoutingProvider: no pre-wired route for given endpoints')
        return RouteResult(
            distance_miles=entry['distance_miles'],
            geometry_geojson=json.dumps(entry['geometry']),
            duration_seconds=entry.get('duration_seconds'),
        )
