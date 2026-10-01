from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from routing.services.corridor import CandidateStation
from routing.services.errors import NoFeasiblePlanError
from routing.services.optimizer import (
    COST_MODEL,
    INFEASIBLE_PLAN_DETAIL,
    ORIGIN_CATCHMENT_MISSING_DETAIL,
    compute_optimized_fuel_plan,
)


def _make_candidate(
    opis_id, price, route_mileage, lat, lon, natural_key_hash,
    name='X', city='C', state='IL',
    distance_from_route_poly_miles: float = 0.1,
):
    rec = SimpleNamespace(
        opis_truckstop_id=opis_id,
        truckstop_name=name,
        address=f'{name} AVE',
        city=city,
        state=state,
        rack_id=f'R{opis_id}',
        retail_price=Decimal(str(price)),
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lon)),
        natural_key_hash=natural_key_hash,
    )
    return CandidateStation(
        record=rec,
        route_mileage=float(route_mileage),
        distance_from_route_poly_miles=distance_from_route_poly_miles,
        natural_key_hash=natural_key_hash,
        retail_price=Decimal(str(price)),
        latitude=Decimal(str(lat)),
        longitude=Decimal(str(lon)),
        opis_truckstop_id=opis_id,
        truckstop_name=name,
        city=city,
        state=state,
    )


def test_optimizer_direct_route_300_miles_case_a():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK-ORIGIN', name='ORIGIN STN')
    dest_mileage = Decimal('300')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin],
        total_route_distance_miles=dest_mileage,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
        origin_catchment_radius_miles_used=Decimal('5'),
    )
    assert plan.cost_model == COST_MODEL
    assert len(plan.stops) == 1
    assert plan.stops[0].is_origin_catchment_entry is True
    assert plan.total_stops == 0
    assert plan.origin_fueled_at_stop_index is None
    assert plan.origin_catchment_station is not None
    expected_gallons = Decimal('300') / Decimal('10')
    assert plan.total_gallons_consumed == (expected_gallons * Decimal('1')).quantize(Decimal('0.0001'))
    assert plan.total_cost == (expected_gallons * Decimal('3.50')).quantize(Decimal('0.01'))


def test_optimizer_700_miles_one_stop_case_b():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1', name='ORIGIN')
    middle = _make_candidate(2, '3.20', 350.0, 41.5, -90.0, 'NK2', name='MID')
    total = Decimal('700')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin, middle],
        total_route_distance_miles=total,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
        origin_catchment_radius_miles_used=Decimal('5'),
    )
    assert plan.cost_model == COST_MODEL
    assert len(plan.stops) == 2
    assert plan.stops[0].is_origin_catchment_entry is True
    assert plan.stops[1].is_origin_catchment_entry is False
    assert plan.total_stops == 1
    assert plan.origin_fueled_at_stop_index is None
    sum_gallons = sum(s.segment_gallons_consumed for s in plan.stops)
    sum_costs = sum(s.segment_cost for s in plan.stops)
    assert plan.total_gallons_consumed == sum_gallons
    assert plan.total_cost == sum_costs


def test_optimizer_multistop_1400_case_c():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1', name='ORIGIN')
    s1 = _make_candidate(2, '3.20', 350.0, 41.5, -90.0, 'NK2', name='S1')
    s2 = _make_candidate(3, '3.10', 700.0, 41.3, -93.5, 'NK3', name='S2')
    s3 = _make_candidate(4, '3.00', 1050.0, 41.2, -97.0, 'NK4', name='S3')
    total = Decimal('1400')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin, s1, s2, s3],
        total_route_distance_miles=total,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
        origin_catchment_radius_miles_used=Decimal('5'),
    )
    assert plan.cost_model == COST_MODEL
    assert plan.stops[0].is_origin_catchment_entry is True
    assert plan.total_stops == sum(1 for s in plan.stops if not s.is_origin_catchment_entry)
    sum_gallons = sum(s.segment_gallons_consumed for s in plan.stops)
    sum_costs = sum(s.segment_cost for s in plan.stops)
    assert plan.total_gallons_consumed == sum_gallons
    assert plan.total_cost == sum_costs


def test_optimizer_infeasible_impossible_stretch_case_d():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1')
    total = Decimal('600')
    with pytest.raises(NoFeasiblePlanError) as exc_info:
        compute_optimized_fuel_plan(
            origin_catchment_station=origin,
            corridor_candidates=[origin],
            total_route_distance_miles=total,
            max_range_miles=Decimal('500'),
            miles_per_gallon=Decimal('10'),
        )
    assert exc_info.value.detail in (INFEASIBLE_PLAN_DETAIL, ORIGIN_CATCHMENT_MISSING_DETAIL)


def test_optimizer_origin_catchment_none_422_case_e():
    with pytest.raises(NoFeasiblePlanError) as exc_info:
        compute_optimized_fuel_plan(
            origin_catchment_station=None,
            corridor_candidates=[],
            total_route_distance_miles=Decimal('100'),
            max_range_miles=Decimal('500'),
            miles_per_gallon=Decimal('10'),
        )
    assert exc_info.value.detail == ORIGIN_CATCHMENT_MISSING_DETAIL


def test_optimizer_no_retroactive_pricing_case_f():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1', name='ORIGIN')
    mid = _make_candidate(2, '2.00', 250.0, 41.5, -90.0, 'NK2', name='MID')
    total = Decimal('500')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin, mid],
        total_route_distance_miles=total,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
    )
    seg_origin = plan.stops[0]
    assert seg_origin.segment_cost <= (Decimal('250') / Decimal('10')) * Decimal('3.50') + Decimal('0.02')


def test_optimizer_total_gallons_sum_match_case_g():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1')
    s1 = _make_candidate(2, '3.20', 350.0, 41.5, -90.0, 'NK2')
    s2 = _make_candidate(3, '3.00', 700.0, 41.3, -95.0, 'NK3')
    total = Decimal('1000')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin, s1, s2],
        total_route_distance_miles=total,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
    )
    sum_gallons = sum(s.segment_gallons_consumed for s in plan.stops)
    assert plan.total_gallons_consumed == sum_gallons


def test_optimizer_total_cost_sum_match_case_h():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1')
    s1 = _make_candidate(2, '3.20', 350.0, 41.5, -90.0, 'NK2')
    total = Decimal('700')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin, s1],
        total_route_distance_miles=total,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
    )
    sum_cost = sum(s.segment_cost for s in plan.stops)
    assert plan.total_cost == sum_cost


def test_optimizer_origin_stops_counting_case_i():
    origin = _make_candidate(1, '3.50', 0.0, 41.88, -87.62, 'NK1')
    s1 = _make_candidate(2, '3.20', 350.0, 41.5, -90.0, 'NK2')
    s2 = _make_candidate(3, '3.00', 700.0, 41.3, -95.0, 'NK3')
    total = Decimal('1000')
    plan = compute_optimized_fuel_plan(
        origin_catchment_station=origin,
        corridor_candidates=[origin, s1, s2],
        total_route_distance_miles=total,
        max_range_miles=Decimal('500'),
        miles_per_gallon=Decimal('10'),
    )
    non_origin_stops = [s for s in plan.stops if not s.is_origin_catchment_entry]
    assert plan.total_stops == len(non_origin_stops)
    assert len(plan.stops) - 1 == plan.total_stops
    assert plan.stops[0].is_origin_catchment_entry is True
