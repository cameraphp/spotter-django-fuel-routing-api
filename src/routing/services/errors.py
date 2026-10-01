class _BaseRoutingError(Exception):
    code: str = 'ROUTING_ERROR'
    status_code: int = 500

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.__class__.code
        super().__init__(self.detail)


class USAValidationError(_BaseRoutingError):
    code = 'USA_VALIDATION_FAILED'
    status_code = 400


class NoFeasiblePlanError(_BaseRoutingError):
    code = 'NO_FEASIBLE_FUEL_PLAN'
    status_code = 422


ORIGIN_CATCHMENT_MISSING_DETAIL = (
    'No fuel station with coordinates is available near the route origin '
    'under the configured origin catchment radius.'
)

INFEASIBLE_PLAN_DETAIL = (
    'No feasible fuel-stop sequence exists for this route under the '
    'configured max range, origin catchment radius, corridor width, '
    'and available stations with coordinates.'
)


class StationCoordinatesNotPrepared(_BaseRoutingError):
    code = 'STATION_COORDINATES_NOT_PREPARED'
    status_code = 428


STATION_COORDS_NOT_PREPARED_DETAIL = (
    'STATION_COORDINATES_NOT_PREPARED — zero fuel station records with '
    'latitude/longitude. Run `python manage.py load_demo_fixture` or '
    '`python manage.py geocode_stations --csv path/to.csv --limit N` '
    'before planning routes.'
)


class ProviderError(_BaseRoutingError):
    code = 'PROVIDER_ERROR'
    status_code = 502


class ProviderTimeout(_BaseRoutingError):
    code = 'PROVIDER_TIMEOUT'
    status_code = 504
