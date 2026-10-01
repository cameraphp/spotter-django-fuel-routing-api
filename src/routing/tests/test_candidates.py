from __future__ import annotations

from decimal import Decimal

from routing.services.corridor import (
    haversine_miles,
    point_to_segment_distance_miles,
)
from routing.services.usa_bbox import is_usa_heuristic


def test_haversine_same_point_zero():
    assert abs(haversine_miles(41.0, -87.0, 41.0, -87.0)) < 1e-6


def test_haversine_chicago_to_denver_reasonable():
    d = haversine_miles(41.881832, -87.623177, 39.739200, -104.990300)
    assert 800.0 < d < 1200.0


def test_point_to_segment_distance_unit():
    d = point_to_segment_distance_miles(0.1, 0.1, 0.0, 0.0, 0.0, 1.0)
    assert 0.0 <= d < 1000.0


def test_is_usa_heuristic_chicago_inside():
    assert is_usa_heuristic(Decimal('41.88'), Decimal('-87.62')) is True


def test_is_usa_heuristic_london_outside():
    assert is_usa_heuristic(Decimal('51.5074'), Decimal('-0.1278')) is False
