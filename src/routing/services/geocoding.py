from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from django.conf import settings

from routing.models import GeocodeCache
from routing.services.errors import ProviderError, ProviderTimeout


class _DecimalSafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return f'{o:f}'
        return super().default(o)


def _json_dumps_safe(value: Any) -> str:
    return json.dumps(value, cls=_DecimalSafeEncoder, sort_keys=True)


@dataclass
class GeocodeResult:
    latitude: Decimal | None
    longitude: Decimal | None
    country_code: str | None = None
    state_code: str | None = None
    display_name: str | None = None
    raw: dict[str, Any] | None = None


def _cache_key(query_type: str, query_input: str) -> str:
    return hashlib.sha256(
        f'{query_type}:{query_input}'.encode('utf-8')
    ).hexdigest()


class GeocodeProvider(ABC):
    def __init__(self) -> None:
        self.cache_hit = False
        self.external_calls = 0

    @abstractmethod
    def geocode(self, query: str, country_codes: str | None = 'us') -> GeocodeResult: ...

    @abstractmethod
    def reverse(self, latitude: Decimal, longitude: Decimal) -> GeocodeResult: ...


class NominatimGeocoder(GeocodeProvider):
    def __init__(
        self,
        base_url: str | None = None,
        user_agent: str | None = None,
        timeout_seconds: int | None = None,
        http_client: httpx.Client | None = None,
        pacing_seconds: float = 0.0,
    ) -> None:
        super().__init__()
        self.base_url = (base_url or settings.NOMINATIM_URL).rstrip('/')
        self.user_agent = user_agent or settings.NOMINATIM_USER_AGENT
        self.timeout = timeout_seconds or settings.NOMINATIM_TIMEOUT_SECONDS
        self.pacing_seconds = pacing_seconds
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self.timeout,
            headers={'User-Agent': self.user_agent},
        )
        self._last_request_at: float = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _pace(self) -> None:
        if self.pacing_seconds <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < self.pacing_seconds:
            time.sleep(self.pacing_seconds - elapsed)

    def _request(self, endpoint: str, params: dict[str, Any]) -> Any:
        url = f'{self.base_url}/{endpoint}'
        params.setdefault('format', 'json')
        self._pace()
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f'Nominatim timeout: {exc}') from exc
        except (httpx.TransportError, httpx.HTTPError) as exc:
            raise ProviderError(f'Nominatim transport error: {exc}') from exc
        self._last_request_at = time.monotonic()
        self.external_calls += 1
        if response.status_code >= 500:
            raise ProviderError(f'Nominatim HTTP {response.status_code}: {response.text[:200]}')
        if response.status_code in (429,):
            raise ProviderTimeout(f'Nominatim rate-limit HTTP {response.status_code}')
        if response.status_code >= 400:
            raise ProviderError(f'Nominatim HTTP {response.status_code}: {response.text[:200]}')
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f'Nominatim invalid JSON response: {exc}') from exc

    def geocode(self, query: str, country_codes: str | None = 'us') -> GeocodeResult:
        params: dict[str, Any] = {'q': query, 'limit': 1, 'addressdetails': 1}
        if country_codes:
            params['countrycodes'] = country_codes
        data = self._request('search', params)
        if not data:
            return GeocodeResult(None, None)
        hit = data[0] if isinstance(data, list) else data
        return GeocodeResult(
            latitude=Decimal(str(hit['lat'])) if 'lat' in hit else None,
            longitude=Decimal(str(hit['lon'])) if 'lon' in hit else None,
            country_code=hit.get('address', {}).get('country_code') or None,
            state_code=hit.get('address', {}).get('state') or None,
            display_name=hit.get('display_name'),
            raw=hit if isinstance(hit, dict) else None,
        )

    def reverse(self, latitude: Decimal, longitude: Decimal) -> GeocodeResult:
        params = {'lat': str(latitude), 'lon': str(longitude), 'zoom': 10, 'addressdetails': 1}
        hit = self._request('reverse', params)
        if not hit or (isinstance(hit, dict) and hit.get('error')):
            return GeocodeResult(None, None)
        return GeocodeResult(
            latitude=Decimal(str(hit['lat'])) if 'lat' in hit else None,
            longitude=Decimal(str(hit['lon'])) if 'lon' in hit else None,
            country_code=hit.get('address', {}).get('country_code') or None,
            state_code=hit.get('address', {}).get('state') or None,
            display_name=hit.get('display_name'),
            raw=hit if isinstance(hit, dict) else None,
        )


class CachedGeocoder(GeocodeProvider):
    def __init__(self, inner: GeocodeProvider) -> None:
        self.inner = inner
        super().__init__()

    @property
    def external_calls(self) -> int:
        return self.inner.external_calls

    @external_calls.setter
    def external_calls(self, value: int) -> None:
        self.inner.external_calls = value

    def geocode(self, query: str, country_codes: str | None = 'us') -> GeocodeResult:
        q_input = _json_dumps_safe({'q': query, 'cc': country_codes})
        key = _cache_key('geocode', q_input)
        cached = GeocodeCache.objects.filter(cache_key=key).first()
        if cached is not None:
            self.cache_hit = True
            return GeocodeResult(
                latitude=cached.latitude,
                longitude=cached.longitude,
                country_code=cached.country_code,
                state_code=cached.state_code,
                display_name=cached.display_name,
                raw=json.loads(cached.raw_json) if cached.raw_json else None,
            )
        self.cache_hit = False
        result = self.inner.geocode(query, country_codes=country_codes)
        GeocodeCache.objects.create(
            cache_key=key,
            query_type='geocode',
            query_input=q_input,
            latitude=result.latitude,
            longitude=result.longitude,
            display_name=result.display_name,
            country_code=result.country_code,
            state_code=result.state_code,
            raw_json=_json_dumps_safe(result.raw) if result.raw else None,
        )
        return result

    def reverse(self, latitude: Decimal, longitude: Decimal) -> GeocodeResult:
        q_input = _json_dumps_safe({'lat': str(latitude), 'lon': str(longitude)})
        key = _cache_key('reverse', q_input)
        cached = GeocodeCache.objects.filter(cache_key=key).first()
        if cached is not None:
            self.cache_hit = True
            return GeocodeResult(
                latitude=cached.latitude,
                longitude=cached.longitude,
                country_code=cached.country_code,
                state_code=cached.state_code,
                display_name=cached.display_name,
                raw=json.loads(cached.raw_json) if cached.raw_json else None,
            )
        self.cache_hit = False
        result = self.inner.reverse(latitude, longitude)
        GeocodeCache.objects.create(
            cache_key=key,
            query_type='reverse',
            query_input=q_input,
            latitude=result.latitude,
            longitude=result.longitude,
            display_name=result.display_name,
            country_code=result.country_code,
            state_code=result.state_code,
            raw_json=_json_dumps_safe(result.raw) if result.raw else None,
        )
        return result
