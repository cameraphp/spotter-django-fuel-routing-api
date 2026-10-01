from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from decimal import Decimal

import pytest

from routing.models import FuelPriceRecord
from routing.tests.mocks import MockGeocoder, MockRoutingProvider

_CSV_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'prompts'))
_WS_RE = re.compile(r'\s+')


def _norm(v): return _WS_RE.sub(' ', (v or '').strip())


def _nk(n, a, c, s):
    parts = [_norm(n).upper(), _norm(a).upper(), _norm(c).upper(), _norm(s).upper()]
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()


CSV_PATH = os.path.join(_CSV_DIR, 'fuel-prices-for-be-assessment.csv')


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    pass


@pytest.fixture(scope='function')
def small_csv(tmp_path):
    path = tmp_path / 'small.csv'
    rows = [
        ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID', 'Retail Price'],
        ['101', 'PILOT #1', 'I-80 EXIT 1', 'CHICAGO', 'IL', '1001', '3.500'],
        ['102', 'SHELL #2', 'I-80 EXIT 100', 'Davenport', 'IA', '1002', '3.250'],
        ['103', 'PILOT #3', 'I-80 EXIT 200', 'DES MOINES', 'IA', '1003', '3.100'],
        ['104', 'KWIK #4', 'I-80 EXIT 300', 'OMAHA', 'NE', '1004', 'BAD_PRICE'],
        ['105', 'LOVES #5', 'I-80 EXIT 400', 'Grand Island', 'NE', '1005', ' 3.050 '],
        ['106', 'PILOT #1 DUP', 'I-80 EXIT 1', 'CHICAGO', 'IL', '1001', '3.400'],
    ]
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return str(path)


@pytest.fixture(scope='function')
def db_populated_with_coords(django_db_blocker):
    stations: list[FuelPriceRecord] = []
    with django_db_blocker.unblock():
        existing_nk = set()

        def add(opis_id, name, addr, city, state, rack, price, lat, lon):
            nkh = _nk(name, addr, city, state)
            if nkh in existing_nk:
                return
            existing_nk.add(nkh)
            rec = FuelPriceRecord.objects.create(
                opis_truckstop_id=opis_id,
                truckstop_name=name,
                address=addr,
                city=city,
                state=state,
                rack_id=rack,
                retail_price=Decimal(str(price)),
                natural_key_hash=nkh,
                source_row_id=opis_id,
                source_file='__test_fixture__',
                latitude=Decimal(str(lat)),
                longitude=Decimal(str(lon)),
            )
            stations.append(rec)

        add(1001, 'CHICAGO ORIGIN STN', 'I-90/I-94 JCT', 'CHICAGO', 'IL', 'R1001', '3.50', 41.881832, -87.623177)
        add(1002, 'JOLIET STN', 'I-80 EXIT 130', 'JOLIET', 'IL', 'R1002', '3.30', 41.520000, -88.150000)
        add(1003, 'DAVENPORT STN', 'I-80 EXIT 290', 'DAVENPORT', 'IA', 'R1003', '3.20', 41.523600, -90.577600)
        add(1004, 'DES MOINES STN', 'I-80 EXIT 130', 'DES MOINES', 'IA', 'R1004', '3.10', 41.600000, -93.620000)
        add(1005, 'OMAHA STN', 'I-80 EXIT 448', 'OMAHA', 'NE', 'R1005', '3.05', 41.250000, -96.000000)
        add(1006, 'GRAND ISLAND STN', 'I-80 EXIT 312', 'GRAND ISLAND', 'NE', 'R1006', '3.00', 40.920000, -98.340000)
        add(1007, 'NORTH PLATTE STN', 'I-80 EXIT 177', 'NORTH PLATTE', 'NE', 'R1007', '2.95', 41.140000, -100.760000)
        add(1008, 'CHEYENNE STN', 'I-80 EXIT 364', 'CHEYENNE', 'WY', 'R1008', '3.15', 41.140000, -104.800000)
        add(1009, 'DENVER DEST STN', 'I-70 EXIT 280', 'DENVER', 'CO', 'R1009', '3.40', 39.739200, -104.990300)
        add(1010, 'LINCOLN NEARBY STN', 'I-80 EXIT 401', 'LINCOLN', 'NE', 'R1010', '3.08', 40.800000, -96.680000)
    return stations


@pytest.fixture(scope='function')
def mock_geocoder():
    g = MockGeocoder()
    g.add('Chicago, IL', Decimal('41.881832'), Decimal('-87.623177'), 'us', 'IL')
    g.add('Denver, CO', Decimal('39.739200'), Decimal('-104.990300'), 'us', 'CO')
    g.add('I-80 & I-94 Chicago IL', Decimal('41.881832'), Decimal('-87.623177'), 'us', 'IL')
    g.add('Toronto, ON', Decimal('43.6532'), Decimal('-79.3832'), 'ca', 'ON')
    return g


@pytest.fixture(scope='function')
def mock_router():
    r = MockRoutingProvider()
    r.add(41.881832, -87.623177, 39.739200, -104.990300, Decimal('1000.000'), n_points=40)
    r.add(41.881832, -87.623177, 41.523600, -90.577600, Decimal('180.000'), n_points=10)
    return r


@pytest.fixture(scope='function')
def provider_overrides(mock_geocoder, mock_router, monkeypatch):
    import routing.planner as planner_mod

    def _fake_geocoder():
        return mock_geocoder

    def _fake_router():
        return mock_router

    monkeypatch.setattr(planner_mod, '_make_geocoder', _fake_geocoder)
    monkeypatch.setattr(planner_mod, '_make_router', _fake_router)
    return {
        'geocoder': mock_geocoder,
        'router': mock_router,
    }


@pytest.fixture(scope='session')
def demo_fixture_path():
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fixtures', 'demo_stations_with_approximate_coordinates.json'))
    return root


@pytest.fixture(scope='session')
def demo_fixture_provenance(demo_fixture_path):
    if not os.path.exists(demo_fixture_path):
        return None
    with open(demo_fixture_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('_provenance') or {}
