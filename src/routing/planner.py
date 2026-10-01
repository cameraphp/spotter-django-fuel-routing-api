from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings

from routing.models import FuelPriceRecord
from routing.services.corridor import (
    find_origin_catchment_station,
    parse_linestring_coords,
    select_corridor_candidates,
)
from routing.services.errors import (
    ORIGIN_CATCHMENT_MISSING_DETAIL,
    STATION_COORDS_NOT_PREPARED_DETAIL,
    NoFeasiblePlanError,
    StationCoordinatesNotPrepared,
    USAValidationError,
)
from routing.services.geocoding import (
    CachedGeocoder,
    GeocodeProvider,
    GeocodeResult,
    NominatimGeocoder,
)
from routing.services.optimizer import (
    FuelOptimizerPlan,
    compute_optimized_fuel_plan,
)
from routing.services.routing import (
    CachedRoutingProvider,
    OSRMRoutingProvider,
    RouteResult,
    RoutingProvider,
)
from routing.services.usa_bbox import is_usa_heuristic

USA_FAIL_TEXT = (
    'Both start and finish waypoints must resolve to the United States '
    '(country_code == "us"). Coordinate inputs use a bounding-box heuristic; '
    'text inputs are validated via Nominatim with countrycodes=us.'
)


@dataclass
class _ResolvedCoords:
    latitude: Decimal
    longitude: Decimal
    country_code: str | None
    state_code: str | None
    display_name: str | None


def _make_geocoder() -> GeocodeProvider:
    return CachedGeocoder(NominatimGeocoder())


def _make_router() -> RoutingProvider:
    return CachedRoutingProvider(OSRMRoutingProvider())


def _resolve_waypoint(
    is_text: bool,
    payload: Any,
    geocoder: GeocodeProvider,
) -> _ResolvedCoords:
    if not is_text:
        lat, lon = payload
        if not is_usa_heuristic(lat, lon):
            raise USAValidationError(USA_FAIL_TEXT)
        return _ResolvedCoords(
            latitude=Decimal(str(lat)),
            longitude=Decimal(str(lon)),
            country_code=None,
            state_code=None,
            display_name=None,
        )
    query = str(payload)
    result: GeocodeResult = geocoder.geocode(query, country_codes='us')
    if result.latitude is None or result.longitude is None:
        raise USAValidationError(
            f'Waypoint could not be geocoded within the USA: {query!r}'
        )
    cc = (result.country_code or '').lower()
    if cc and cc != 'us':
        raise USAValidationError(USA_FAIL_TEXT)
    return _ResolvedCoords(
        latitude=result.latitude,
        longitude=result.longitude,
        country_code=result.country_code,
        state_code=result.state_code,
        display_name=result.display_name,
    )


def _count_stats() -> tuple[int, int]:
    total = FuelPriceRecord.objects.count()
    with_coords = FuelPriceRecord.objects.filter(
        latitude__isnull=False, longitude__isnull=False
    ).count()
    return total, with_coords


def _assemble_response(
    route_result: RouteResult,
    max_range_miles: Decimal,
    miles_per_gallon: Decimal,
    plan: FuelOptimizerPlan,
    stations_considered: int,
    candidate_station_count: int,
    total_external_calls: int,
    total_cache_hits: int,
) -> dict[str, Any]:
    geometry = json.loads(route_result.geometry_geojson)
    total_records, with_coords = _count_stats()
    estimated_gallons = (
        Decimal(str(route_result.distance_miles)) / Decimal(str(miles_per_gallon))
    )
    from routing.services.optimizer import QUANT_GAL, QUANT_MI, _q

    fuel_stops_payload: list[dict[str, Any]] = []
    for stop in plan.stops:
        station = stop.station
        fuel_stops_payload.append({
            'is_origin_catchment_entry': stop.is_origin_catchment_entry,
            'station': {
                'opis_truckstop_id': station.opis_truckstop_id,
                'truckstop_name': station.truckstop_name,
                'address': station.address,
                'city': station.city,
                'state': station.state,
                'rack_id': station.rack_id,
                'retail_price': station.retail_price,
                'latitude': station.latitude,
                'longitude': station.longitude,
                'natural_key_hash': station.natural_key_hash,
            },
            'route_mileage_at_departure': stop.route_mileage_at_departure,
            'next_stop_route_mileage': stop.next_stop_route_mileage,
            'segment_miles': stop.segment_miles,
            'segment_gallons_consumed': stop.segment_gallons_consumed,
            'segment_cost': stop.segment_cost,
            'distance_from_route_poly_miles': stop.distance_from_route_poly_miles,
        })
    origin_station_payload: dict[str, Any] | None = None
    if plan.origin_catchment_station is not None:
        s = plan.origin_catchment_station
        origin_station_payload = {
            'opis_truckstop_id': s.opis_truckstop_id,
            'truckstop_name': s.truckstop_name,
            'address': s.address,
            'city': s.city,
            'state': s.state,
            'rack_id': s.rack_id,
            'retail_price': s.retail_price,
            'latitude': s.latitude,
            'longitude': s.longitude,
            'natural_key_hash': s.natural_key_hash,
        }

    from routing.serializers import ASSUMPTIONS_PAYLOAD

    return {
        'route': {
            'distance_miles': _q(Decimal(str(route_result.distance_miles)), QUANT_MI),
            'duration_seconds': (
                _q(Decimal(str(route_result.duration_seconds)), Decimal('0.01'))
                if route_result.duration_seconds is not None
                else None
            ),
            'geometry': geometry,
        },
        'vehicle': {
            'max_range_miles': _q(Decimal(str(max_range_miles)), QUANT_MI),
            'miles_per_gallon': _q(Decimal(str(miles_per_gallon)), Decimal('0.001')),
        },
        'estimated_fuel_consumed_gallons': _q(estimated_gallons, QUANT_GAL),
        'fuel_plan': {
            'cost_model': plan.cost_model,
            'stops': fuel_stops_payload,
            'total_gallons_consumed': plan.total_gallons_consumed,
            'total_cost': plan.total_cost,
            'total_stops': plan.total_stops,
            'origin_fueled_at_stop_index': plan.origin_fueled_at_stop_index,
            'origin_catchment_radius_miles_used': plan.origin_catchment_radius_miles_used,
            'origin_catchment_station': origin_station_payload,
        },
        'assumptions': dict(ASSUMPTIONS_PAYLOAD),
        'data_quality': {
            'fuel_station_records_loaded': int(total_records),
            'stations_with_coordinates': int(with_coords),
            'stations_considered': int(stations_considered),
            'candidate_station_count': int(candidate_station_count),
            'external_provider_calls': int(total_external_calls),
            'cache_hits': int(total_cache_hits),
        },
    }


def plan_route(
    request_payload: dict[str, Any],
    geocoder: GeocodeProvider | None = None,
    router: RoutingProvider | None = None,
) -> dict[str, Any]:
    from routing.serializers import PlanRequestSerializer

    sr = PlanRequestSerializer(data=request_payload)
    sr.is_valid(raise_exception=True)
    v = sr.validated_data

    start = v['start']
    finish = v['finish']
    vehicle = v.get('vehicle') or {}
    max_range = Decimal(str(vehicle.get('max_range_miles', 500)))
    mpg = Decimal(str(vehicle.get('miles_per_gallon', 10)))

    total_records, with_coords = _count_stats()
    if with_coords <= 0:
        raise StationCoordinatesNotPrepared(STATION_COORDS_NOT_PREPARED_DETAIL)

    owns_geocoder = geocoder is None
    owns_router = router is None
    if geocoder is None:
        geocoder = _make_geocoder()
    if router is None:
        router = _make_router()

    total_external = 0
    total_cache_hits = 0

    try:
        start_resolved = _resolve_waypoint(start['is_text'], start['payload'], geocoder)
        total_external += int(getattr(geocoder, 'external_calls', 0))
        total_cache_hits += int(getattr(geocoder, 'cache_hit', False))
    except Exception:
        if owns_geocoder and hasattr(geocoder, 'inner') and hasattr(geocoder.inner, 'close'):
            geocoder.inner.close()
        raise

    try:
        finish_resolved = _resolve_waypoint(finish['is_text'], finish['payload'], geocoder)
        total_external += int(getattr(geocoder, 'external_calls', 0) - (total_external - total_cache_hits))
        if bool(getattr(geocoder, 'cache_hit', False)):
            total_cache_hits += 1
    except Exception:
        if owns_geocoder and hasattr(geocoder, 'inner') and hasattr(geocoder.inner, 'close'):
            geocoder.inner.close()
        raise

    try:
        route_result: RouteResult = router.route(
            start_resolved.latitude,
            start_resolved.longitude,
            finish_resolved.latitude,
            finish_resolved.longitude,
        )
        total_external += int(getattr(router, 'external_calls', 0))
        if bool(getattr(router, 'cache_hit', False)):
            total_cache_hits += 1
    except Exception:
        if owns_router and hasattr(router, 'inner') and hasattr(router.inner, 'close'):
            router.inner.close()
        if owns_geocoder and hasattr(geocoder, 'inner') and hasattr(geocoder.inner, 'close'):
            geocoder.inner.close()
        raise

    route_coords = parse_linestring_coords(route_result.geometry_geojson)
    stations_q = FuelPriceRecord.objects.filter(
        latitude__isnull=False, longitude__isnull=False
    )
    candidates, stations_considered, pre_dedupe_count = select_corridor_candidates(
        route_coords,
        list(stations_q),
        corridor_width_miles=float(settings.CORRIDOR_WIDTH_MILES),
    )
    candidate_station_count = len(candidates)

    origin_catch = find_origin_catchment_station(
        start_resolved.latitude,
        start_resolved.longitude,
        candidates,
        origin_catchment_radius_miles=float(settings.ORIGIN_CATCHMENT_RADIUS_MILES),
    )
    if origin_catch is None and candidates:
        origin_catch = find_origin_catchment_station(
            start_resolved.latitude,
            start_resolved.longitude,
            candidates,
            origin_catchment_radius_miles=float(settings.ORIGIN_CATCHMENT_RADIUS_MILES) * 2.0,
        )

    if origin_catch is None:
        origin_catch = find_origin_catchment_station(
            start_resolved.latitude,
            start_resolved.longitude,
            candidates,
            origin_catchment_radius_miles=float(settings.ORIGIN_CATCHMENT_RADIUS_MILES) * 5.0,
        )
    if origin_catch is None:
        if owns_router and hasattr(router, 'inner') and hasattr(router.inner, 'close'):
            router.inner.close()
        if owns_geocoder and hasattr(geocoder, 'inner') and hasattr(geocoder.inner, 'close'):
            geocoder.inner.close()
        raise NoFeasiblePlanError(ORIGIN_CATCHMENT_MISSING_DETAIL)

    try:
        plan: FuelOptimizerPlan = compute_optimized_fuel_plan(
            origin_catchment_station=origin_catch,
            corridor_candidates=candidates,
            total_route_distance_miles=Decimal(str(route_result.distance_miles)),
            max_range_miles=max_range,
            miles_per_gallon=mpg,
            origin_catchment_radius_miles_used=Decimal(str(settings.ORIGIN_CATCHMENT_RADIUS_MILES)),
        )
    except NoFeasiblePlanError:
        if owns_router and hasattr(router, 'inner') and hasattr(router.inner, 'close'):
            router.inner.close()
        if owns_geocoder and hasattr(geocoder, 'inner') and hasattr(geocoder.inner, 'close'):
            geocoder.inner.close()
        raise

    if owns_router and hasattr(router, 'inner') and hasattr(router.inner, 'close'):
        router.inner.close()
    if owns_geocoder and hasattr(geocoder, 'inner') and hasattr(geocoder.inner, 'close'):
        geocoder.inner.close()

    return _assemble_response(
        route_result,
        max_range,
        mpg,
        plan,
        stations_considered,
        candidate_station_count,
        total_external,
        total_cache_hits,
    )
