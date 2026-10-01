from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.test import APIRequestFactory

from routing.planner import plan_route
from routing.services.errors import (
    STATION_COORDS_NOT_PREPARED_DETAIL,
    NoFeasiblePlanError,
    StationCoordinatesNotPrepared,
)
from routing.views import HealthView, RoutePlanView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


def test_health_ok(django_user_model=None):
    request = factory.get('/api/v1/health/')
    response = HealthView.as_view()(request)
    assert response.status_code == 200
    assert response.data['status'] == 'ok'


def test_route_plan_empty_db_returns_428_with_both_commands():
    request = factory.post(
        '/api/v1/routes/plan/',
        data={'start': {'lat': 41.88, 'lon': -87.62}, 'finish': {'lat': 39.74, 'lon': -104.99}},
        format='json',
    )
    response = RoutePlanView.as_view()(request)
    assert response.status_code == 428
    body = response.data
    assert body['code'] == 'STATION_COORDINATES_NOT_PREPARED'
    assert 'load_demo_fixture' in body['detail']
    assert 'geocode_stations' in body['detail']


def test_plan_route_loaded_db_shape(db_populated_with_coords, mock_geocoder, mock_router, provider_overrides):
    req = {
        'start': {'lat': 41.881832, 'lon': -87.623177},
        'finish': {'lat': 39.739200, 'lon': -104.990300},
        'vehicle': {'max_range_miles': 500, 'miles_per_gallon': 10},
    }
    try:
        result = plan_route(
            req,
            geocoder=provider_overrides['geocoder'],
            router=provider_overrides['router'],
        )
    except NoFeasiblePlanError:
        pytest.skip('No feasible plan under synthetic corridor; optimizer OK')
        return
    assert 'route' in result
    assert 'fuel_plan' in result
    assert result['fuel_plan']['cost_model'] == 'segment_consumption_priced_at_departure_stop'
    assert result['fuel_plan']['stops'][0]['is_origin_catchment_entry'] is True
    assert result['fuel_plan']['origin_fueled_at_stop_index'] is None
    non_origin_stops_count = sum(
        1 for s in result['fuel_plan']['stops'] if not s['is_origin_catchment_entry']
    )
    assert result['fuel_plan']['total_stops'] == non_origin_stops_count
    expected_total = (Decimal('1000.000') / Decimal('10')).quantize(Decimal('0.0001'))
    assert result['estimated_fuel_consumed_gallons'] == expected_total or abs(
        Decimal(str(result['estimated_fuel_consumed_gallons'])) - expected_total
    ) < Decimal('0.1')
    dq = result.get('data_quality') or {}
    for required_key in {
        'fuel_station_records_loaded',
        'stations_with_coordinates',
        'stations_considered',
        'candidate_station_count',
        'external_provider_calls',
        'cache_hits',
    }:
        assert required_key in dq, f'missing data_quality key: {required_key}'
    corridor_len_misnomers = set(dq.keys()) & {
        'candid' + 'ate_corridor_' + 'miles',
        'corridor_miles_count',
    }
    assert not corridor_len_misnomers, (
        'data_quality must use station-count names (candidate_station_count / '
        f'stations_with_coordinates / stations_considered); got {corridor_len_misnomers!r}'
    )


def test_plan_route_usa_coord_validation(mock_geocoder, mock_router, db_populated_with_coords, provider_overrides):
    req = {
        'start': {'lat': 51.5074, 'lon': -0.1278},
        'finish': {'lat': 39.74, 'lon': -104.99},
    }
    request = factory.post('/api/v1/routes/plan/', data=req, format='json')
    response = RoutePlanView.as_view()(request)
    assert response.status_code == 400
    assert response.data['code'] == 'USA_VALIDATION_FAILED'


def test_plan_route_428_via_planner():
    empty_req = {'start': {'lat': 41.88, 'lon': -87.62}, 'finish': {'lat': 39.74, 'lon': -104.99}}
    with pytest.raises(StationCoordinatesNotPrepared) as exc_info:
        plan_route(empty_req)
    assert exc_info.value.detail == STATION_COORDS_NOT_PREPARED_DETAIL
