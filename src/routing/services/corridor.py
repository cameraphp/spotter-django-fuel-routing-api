from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from django.conf import settings

from routing.models import FuelPriceRecord

EARTH_RADIUS_MILES = 3958.8


def _to_rad(deg: Decimal | float) -> float:
    return float(deg) * (math.pi / 180.0)


def haversine_miles(
    lat1: Decimal | float,
    lon1: Decimal | float,
    lat2: Decimal | float,
    lon2: Decimal | float,
) -> float:
    dlat = _to_rad(lat2 - lat1)
    dlon = _to_rad(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(_to_rad(lat1)) * math.cos(_to_rad(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def point_to_segment_distance_miles(
    p_lat: Decimal | float,
    p_lon: Decimal | float,
    a_lat: Decimal | float,
    a_lon: Decimal | float,
    b_lat: Decimal | float,
    b_lon: Decimal | float,
) -> float:
    lat0, lon0 = float(p_lat), float(p_lon)
    lat1, lon1 = float(a_lat), float(a_lon)
    lat2, lon2 = float(b_lat), float(b_lon)
    mid_lat = (lat1 + lat2) / 2.0
    k_lat = (math.pi / 180.0) * EARTH_RADIUS_MILES
    k_lon = (math.pi / 180.0) * EARTH_RADIUS_MILES * math.cos(mid_lat * math.pi / 180.0)
    x0, y0 = lon0 * k_lon, lat0 * k_lat
    x1, y1 = lon1 * k_lon, lat1 * k_lat
    x2, y2 = lon2 * k_lon, lat2 * k_lat
    dx = x2 - x1
    dy = y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-18:
        dx_seg = x0 - x1
        dy_seg = y0 - y1
        return math.sqrt(dx_seg * dx_seg + dy_seg * dy_seg)
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / len_sq
    t = max(0.0, min(1.0, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return math.sqrt((x0 - px) ** 2 + (y0 - py) ** 2)


def parse_linestring_coords(geometry_geojson_str: str) -> list[tuple[Decimal, Decimal]]:
    geometry = json.loads(geometry_geojson_str)
    if not isinstance(geometry, dict) or geometry.get('type') != 'LineString':
        raise ValueError('geometry_geojson must be a GeoJSON LineString object')
    coords = geometry.get('coordinates', [])
    result: list[tuple[Decimal, Decimal]] = []
    for pair in coords:
        if not isinstance(pair, list) or len(pair) < 2:
            continue
        lon = Decimal(str(pair[0]))
        lat = Decimal(str(pair[1]))
        result.append((lat, lon))
    return result


def cumulative_distance_miles(
    coords: list[tuple[Decimal, Decimal]],
) -> list[float]:
    n = len(coords)
    cum = [0.0] * n
    for i in range(1, n):
        prev = coords[i - 1]
        cur = coords[i]
        cum[i] = cum[i - 1] + haversine_miles(prev[0], prev[1], cur[0], cur[1])
    return cum


@dataclass
class ProjectedPoint:
    prev_idx: int
    next_idx: int
    segment_t: float
    route_mileage: float
    perpendicular_distance_miles: float


def project_onto_route(
    p_lat: Decimal,
    p_lon: Decimal,
    coords: list[tuple[Decimal, Decimal]],
    cumulative: list[float] | None = None,
) -> ProjectedPoint:
    if cumulative is None:
        cumulative = cumulative_distance_miles(coords)
    best_dist = math.inf
    best: ProjectedPoint | None = None
    for i in range(len(coords) - 1):
        a = coords[i]
        b = coords[i + 1]
        mid_lat = (float(a[0]) + float(b[0])) / 2.0
        k_lat = (math.pi / 180.0) * EARTH_RADIUS_MILES
        k_lon = (math.pi / 180.0) * EARTH_RADIUS_MILES * math.cos(mid_lat * math.pi / 180.0)
        x0, y0 = float(p_lon) * k_lon, float(p_lat) * k_lat
        x1, y1 = float(a[1]) * k_lon, float(a[0]) * k_lat
        x2, y2 = float(b[1]) * k_lon, float(b[0]) * k_lat
        dx = x2 - x1
        dy = y2 - y1
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-18:
            t = 0.0
        else:
            t = ((x0 - x1) * dx + (y0 - y1) * dy) / len_sq
            t = max(0.0, min(1.0, t))
        px = x1 + t * dx
        py = y1 + t * dy
        d = math.sqrt((x0 - px) ** 2 + (y0 - py) ** 2)
        if d < best_dist:
            best_dist = d
            seg_len = haversine_miles(a[0], a[1], b[0], b[1])
            route_mileage = cumulative[i] + t * seg_len
            best = ProjectedPoint(
                prev_idx=i,
                next_idx=i + 1,
                segment_t=t,
                route_mileage=route_mileage,
                perpendicular_distance_miles=d,
            )
    if best is None:
        return ProjectedPoint(prev_idx=0, next_idx=0, segment_t=0.0, route_mileage=0.0, perpendicular_distance_miles=math.inf)
    return best


@dataclass
class CandidateStation:
    record: FuelPriceRecord
    route_mileage: float
    distance_from_route_poly_miles: float
    natural_key_hash: str
    retail_price: Decimal
    latitude: Decimal
    longitude: Decimal
    opis_truckstop_id: int
    truckstop_name: str
    city: str
    state: str


def _station_fields(
    record: FuelPriceRecord,
    route_mileage: float,
    distance_from_route_poly_miles: float,
) -> CandidateStation:
    return CandidateStation(
        record=record,
        route_mileage=route_mileage,
        distance_from_route_poly_miles=distance_from_route_poly_miles,
        natural_key_hash=record.natural_key_hash,
        retail_price=record.retail_price,
        latitude=record.latitude,  # type: ignore[arg-type]
        longitude=record.longitude,  # type: ignore[arg-type]
        opis_truckstop_id=record.opis_truckstop_id,
        truckstop_name=record.truckstop_name,
        city=record.city,
        state=record.state,
    )


def select_corridor_candidates(
    route_coords: list[tuple[Decimal, Decimal]],
    stations: Iterable[FuelPriceRecord],
    corridor_width_miles: float | None = None,
) -> tuple[list[CandidateStation], int, int]:
    corridor_width = float(corridor_width_miles or settings.CORRIDOR_WIDTH_MILES)
    cumulative = cumulative_distance_miles(route_coords)
    stations_considered = 0
    inside_corridor: list[CandidateStation] = []
    for station in stations:
        if station.latitude is None or station.longitude is None:
            continue
        stations_considered += 1
        proj = project_onto_route(station.latitude, station.longitude, route_coords, cumulative)
        if proj.perpendicular_distance_miles > corridor_width:
            continue
        inside_corridor.append(
            _station_fields(station, proj.route_mileage, proj.perpendicular_distance_miles)
        )
    by_key: dict[str, CandidateStation] = {}
    for cand in inside_corridor:
        key = cand.natural_key_hash
        existing = by_key.get(key)
        if existing is None or cand.retail_price < existing.retail_price:
            by_key[key] = cand
    deduped = sorted(
        by_key.values(),
        key=lambda c: (c.route_mileage, c.natural_key_hash),
    )
    return deduped, stations_considered, len(inside_corridor)


def find_origin_catchment_station(
    origin_lat: Decimal,
    origin_lon: Decimal,
    candidates: list[CandidateStation],
    origin_catchment_radius_miles: float | None = None,
) -> CandidateStation | None:
    radius = float(origin_catchment_radius_miles or settings.ORIGIN_CATCHMENT_RADIUS_MILES)
    best: CandidateStation | None = None
    best_score: float = math.inf
    for cand in candidates:
        dist_origin_to_station = haversine_miles(
            origin_lat, origin_lon, cand.latitude, cand.longitude
        )
        score = dist_origin_to_station + cand.distance_from_route_poly_miles
        if score > radius:
            continue
        if score < best_score or (
            score == best_score
            and cand.natural_key_hash < best.natural_key_hash  # type: ignore[union-attr]
        ):
            best = cand
            best_score = score
    return best
