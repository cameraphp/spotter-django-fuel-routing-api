from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

import httpx
from django.conf import settings

from routing.models import RouteCache
from routing.services.errors import ProviderError, ProviderTimeout


@dataclass
class RouteResult:
    distance_miles: Decimal
    geometry_geojson: str
    duration_seconds: Decimal | None = None


def _route_cache_key(
    start_latitude: Decimal,
    start_longitude: Decimal,
    end_latitude: Decimal,
    end_longitude: Decimal,
) -> str:
    payload = json.dumps(
        {
            'slat': f'{Decimal(start_latitude):.7f}',
            'slon': f'{Decimal(start_longitude):.7f}',
            'elat': f'{Decimal(end_latitude):.7f}',
            'elon': f'{Decimal(end_longitude):.7f}',
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class RoutingProvider(ABC):
    def __init__(self) -> None:
        self.cache_hit = False
        self.external_calls = 0

    @abstractmethod
    def route(
        self,
        start_latitude: Decimal,
        start_longitude: Decimal,
        end_latitude: Decimal,
        end_longitude: Decimal,
    ) -> RouteResult: ...


class OSRMRoutingProvider(RoutingProvider):
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__()
        self.base_url = (base_url or settings.OSRM_URL).rstrip('/')
        self.timeout = timeout_seconds or settings.NOMINATIM_TIMEOUT_SECONDS
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def route(
        self,
        start_latitude: Decimal,
        start_longitude: Decimal,
        end_latitude: Decimal,
        end_longitude: Decimal,
    ) -> RouteResult:
        coords = f'{start_longitude},{start_latitude};{end_longitude},{end_latitude}'
        url = f'{self.base_url}/route/v1/driving/{coords}'
        params = {'overview': 'full', 'geometries': 'geojson', 'steps': 'false'}
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f'OSRM timeout: {exc}') from exc
        except (httpx.TransportError, httpx.HTTPError) as exc:
            raise ProviderError(f'OSRM transport error: {exc}') from exc
        self.external_calls += 1
        if response.status_code >= 500:
            raise ProviderError(f'OSRM HTTP {response.status_code}: {response.text[:200]}')
        if response.status_code >= 400:
            raise ProviderError(f'OSRM HTTP {response.status_code}: {response.text[:200]}')
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f'OSRM invalid JSON response: {exc}') from exc
        routes = payload.get('routes') or []
        if not routes:
            raise ProviderError('OSRM response has no routes')
        route = routes[0]
        distance_meters = Decimal(str(route.get('distance', 0)))
        duration_seconds = route.get('duration')
        geometry = route.get('geometry')
        if not geometry or not isinstance(geometry, dict) or geometry.get('type') != 'LineString':
            raise ProviderError('OSRM response missing valid GeoJSON LineString geometry')
        distance_miles = distance_meters / Decimal('1609.344')
        return RouteResult(
            distance_miles=distance_miles,
            geometry_geojson=json.dumps(geometry),
            duration_seconds=Decimal(str(duration_seconds)) if duration_seconds is not None else None,
        )


class CachedRoutingProvider(RoutingProvider):
    def __init__(self, inner: RoutingProvider) -> None:
        super().__init__()
        self.inner = inner

    @property
    def external_calls(self) -> int:
        return self.inner.external_calls

    @external_calls.setter
    def external_calls(self, value: int) -> None:
        self.inner.external_calls = value

    def route(
        self,
        start_latitude: Decimal,
        start_longitude: Decimal,
        end_latitude: Decimal,
        end_longitude: Decimal,
    ) -> RouteResult:
        key = _route_cache_key(start_latitude, start_longitude, end_latitude, end_longitude)
        cached = RouteCache.objects.filter(cache_key=key).first()
        if cached is not None:
            self.cache_hit = True
            return RouteResult(
                distance_miles=cached.distance_miles,
                geometry_geojson=cached.geometry_geojson,
                duration_seconds=cached.duration_seconds,
            )
        self.cache_hit = False
        result = self.inner.route(start_latitude, start_longitude, end_latitude, end_longitude)
        RouteCache.objects.create(
            cache_key=key,
            start_latitude=start_latitude,
            start_longitude=start_longitude,
            end_latitude=end_latitude,
            end_longitude=end_longitude,
            distance_miles=result.distance_miles,
            geometry_geojson=result.geometry_geojson,
            duration_seconds=result.duration_seconds,
        )
        return result
