from __future__ import annotations

from decimal import Decimal

import pytest

from routing.services.geocoding import (
    CachedGeocoder,
    GeocodeProvider,
    GeocodeResult,
)
from routing.services.routing import (
    CachedRoutingProvider,
    RouteResult,
    RoutingProvider,
)
from routing.tests.mocks import MockGeocoder


class _NoopGeocoder(GeocodeProvider):
    def geocode(self, query, country_codes='us'):
        self.external_calls += 1
        return GeocodeResult(Decimal('0'), Decimal('0'))

    def reverse(self, latitude, longitude):
        self.external_calls += 1
        return GeocodeResult(None, None)


class _NoopRouter(RoutingProvider):
    def route(self, slat, slon, elat, elon):
        self.external_calls += 1
        return RouteResult(
            Decimal('10'),
            '{"type":"LineString","coordinates":[[0,0],[1,1]]}',
        )


def test_cached_geocoder_init_no_attributeerror_on_external_calls_zero():
    inner = _NoopGeocoder()
    cached = CachedGeocoder(inner)
    assert cached.external_calls == 0
    assert inner.external_calls == 0


def test_cached_geocoder_init_no_attributeerror_on_inner_access():
    inner = _NoopGeocoder()
    cached = CachedGeocoder(inner)
    assert cached.inner is inner


def test_cached_geocoder_external_calls_delegated_after_miss():
    inner = _NoopGeocoder()
    cached = CachedGeocoder(inner)
    inner.geocode('test')
    assert inner.external_calls == 1
    assert cached.external_calls == 1


@pytest.mark.django_db(transaction=True)
def test_cached_geocoder_cache_hit_does_not_increment_inner_counter():
    inner = MockGeocoder()
    inner.add('Chicago, IL', 41.8818, -87.6232, 'us', 'IL')
    cached = CachedGeocoder(inner)
    r1 = cached.geocode('Chicago, IL', country_codes='us')
    after_first = cached.external_calls
    assert after_first == 1
    assert r1.latitude is not None
    r2 = cached.geocode('Chicago, IL', country_codes='us')
    assert cached.cache_hit is True
    assert cached.external_calls == after_first
    assert r2.latitude == r1.latitude


def test_cached_routing_provider_init_no_attributeerror():
    inner = _NoopRouter()
    cached = CachedRoutingProvider(inner)
    assert cached.external_calls == 0
    assert cached.inner is inner
