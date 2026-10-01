from __future__ import annotations

from decimal import Decimal
from typing import Any, Union

from rest_framework import serializers

ASSUMPTIONS_PAYLOAD: dict[str, Any] = {
    'A_1_no_tank_simulation': True,
    'A_2_max_range_is_stretch_limit': True,
    'A_3_cost_model_segment_departure_price': True,
    'A_4_first_segment_priced_at_origin_catchment_station': True,
    'A_5_no_initial_fuel_level_assumed': True,
    'A_6_coord_usa_uses_bounding_box_heuristic_not_reverse_geocode': True,
    'A_7_nominatim_country_us_text_query_validation': True,
    'A_8_station_coords_from_fixture_or_geocode_command_never_runtime': True,
    'A_9_station_dedupe_by_natural_key_lowest_price_kept': True,
    'A_10_corridor_width_25_mi_default': True,
    'A_11_origin_catchment_radius_5_mi_default': True,
    'A_12_no_retroactive_segment_pricing_allowed': True,
    'A_13_osrm_geojson_only_no_polyline_library': True,
}


DEFAULT_MAX_RANGE_MILES = Decimal('500')
DEFAULT_MPG = Decimal('10')


class _CoordinateLatLon:
    pass


CoordinateType = Union[str, dict[str, Any]]


class CoordinateSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=12, decimal_places=7)
    lon = serializers.DecimalField(max_digits=12, decimal_places=7)


class VehicleSpecSerializer(serializers.Serializer):
    max_range_miles = serializers.DecimalField(
        max_digits=12, decimal_places=3, required=False, default=DEFAULT_MAX_RANGE_MILES
    )
    miles_per_gallon = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, default=DEFAULT_MPG
    )


class PlanRequestSerializer(serializers.Serializer):
    start = serializers.JSONField()
    finish = serializers.JSONField()
    vehicle = VehicleSpecSerializer(required=False, default=dict)

    def _normalize_waypoint(self, value: Any) -> tuple[bool, str | tuple[Decimal, Decimal]]:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise serializers.ValidationError('waypoint string must not be empty')
            return True, stripped
        if isinstance(value, dict):
            if 'lat' not in value or 'lon' not in value:
                raise serializers.ValidationError(
                    'waypoint object must have "lat" and "lon" keys'
                )
            try:
                lat = Decimal(str(value['lat']))
                lon = Decimal(str(value['lon']))
            except Exception as exc:
                raise serializers.ValidationError(f'waypoint coord parse error: {exc}') from exc
            return False, (lat, lon)
        raise serializers.ValidationError(
            'waypoint must be a string address or a {lat, lon} JSON object'
        )

    def validate_start(self, value: Any) -> dict[str, Any]:
        is_text, payload = self._normalize_waypoint(value)
        return {'is_text': is_text, 'payload': payload}

    def validate_finish(self, value: Any) -> dict[str, Any]:
        is_text, payload = self._normalize_waypoint(value)
        return {'is_text': is_text, 'payload': payload}


class StationInfoSerializer(serializers.Serializer):
    opis_truckstop_id = serializers.IntegerField()
    truckstop_name = serializers.CharField()
    address = serializers.CharField(required=False, allow_blank=True, default='')
    city = serializers.CharField()
    state = serializers.CharField()
    rack_id = serializers.CharField(required=False, allow_blank=True, default='')
    retail_price = serializers.DecimalField(max_digits=10, decimal_places=4)
    latitude = serializers.DecimalField(max_digits=12, decimal_places=7)
    longitude = serializers.DecimalField(max_digits=12, decimal_places=7)
    natural_key_hash = serializers.CharField(required=False, allow_blank=True, default='')


class FuelStopPlanEntrySerializer(serializers.Serializer):
    is_origin_catchment_entry = serializers.BooleanField()
    station = StationInfoSerializer()
    route_mileage_at_departure = serializers.DecimalField(max_digits=14, decimal_places=3)
    next_stop_route_mileage = serializers.DecimalField(max_digits=14, decimal_places=3)
    segment_miles = serializers.DecimalField(max_digits=14, decimal_places=3)
    segment_gallons_consumed = serializers.DecimalField(max_digits=14, decimal_places=4)
    segment_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    distance_from_route_poly_miles = serializers.DecimalField(max_digits=10, decimal_places=3)


class FuelPlanSerializer(serializers.Serializer):
    cost_model = serializers.CharField()
    stops = FuelStopPlanEntrySerializer(many=True)
    total_gallons_consumed = serializers.DecimalField(max_digits=14, decimal_places=4)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_stops = serializers.IntegerField()
    origin_fueled_at_stop_index = serializers.IntegerField(allow_null=True, default=None)
    origin_catchment_radius_miles_used = serializers.DecimalField(
        max_digits=10, decimal_places=3, allow_null=True
    )
    origin_catchment_station = StationInfoSerializer(allow_null=True, default=None)


class GeometrySerializer(serializers.Serializer):
    type = serializers.CharField()
    coordinates = serializers.ListField(child=serializers.ListField(child=serializers.DecimalField(max_digits=15, decimal_places=8)))


class RouteSerializer(serializers.Serializer):
    distance_miles = serializers.DecimalField(max_digits=14, decimal_places=3)
    duration_seconds = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True, required=False
    )
    geometry = GeometrySerializer()


class VehicleResponseSerializer(serializers.Serializer):
    max_range_miles = serializers.DecimalField(max_digits=12, decimal_places=3)
    miles_per_gallon = serializers.DecimalField(max_digits=10, decimal_places=3)


class AssumptionsSerializer(serializers.Serializer):
    A_1_no_tank_simulation = serializers.BooleanField()
    A_2_max_range_is_stretch_limit = serializers.BooleanField()
    A_3_cost_model_segment_departure_price = serializers.BooleanField()
    A_4_first_segment_priced_at_origin_catchment_station = serializers.BooleanField()
    A_5_no_initial_fuel_level_assumed = serializers.BooleanField()
    A_6_coord_usa_uses_bounding_box_heuristic_not_reverse_geocode = serializers.BooleanField()
    A_7_nominatim_country_us_text_query_validation = serializers.BooleanField()
    A_8_station_coords_from_fixture_or_geocode_command_never_runtime = serializers.BooleanField()
    A_9_station_dedupe_by_natural_key_lowest_price_kept = serializers.BooleanField()
    A_10_corridor_width_25_mi_default = serializers.BooleanField()
    A_11_origin_catchment_radius_5_mi_default = serializers.BooleanField()
    A_12_no_retroactive_segment_pricing_allowed = serializers.BooleanField()
    A_13_osrm_geojson_only_no_polyline_library = serializers.BooleanField()


class DataQualitySerializer(serializers.Serializer):
    fuel_station_records_loaded = serializers.IntegerField()
    stations_with_coordinates = serializers.IntegerField()
    stations_considered = serializers.IntegerField()
    candidate_station_count = serializers.IntegerField()
    external_provider_calls = serializers.IntegerField()
    cache_hits = serializers.IntegerField()


class PlanResponseSerializer(serializers.Serializer):
    route = RouteSerializer()
    vehicle = VehicleResponseSerializer()
    estimated_fuel_consumed_gallons = serializers.DecimalField(max_digits=14, decimal_places=4)
    fuel_plan = FuelPlanSerializer()
    assumptions = AssumptionsSerializer()
    data_quality = DataQualitySerializer()
