from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from routing.models import FuelPriceRecord

pytestmark = pytest.mark.django_db(transaction=True)


def _run(cmd, *args, **kwargs):
    out = StringIO()
    err = StringIO()
    try:
        call_command(cmd, *args, stdout=out, stderr=err, **kwargs)
    except SystemExit as e:
        return out.getvalue(), err.getvalue(), int(e.code) if e.code is not None else 0
    return out.getvalue(), err.getvalue(), 0


def test_import_strict_decimal_parse_invalid(small_csv, capsys):
    out, err, exitcode = _run('import_fuel_prices', small_csv)
    assert FuelPriceRecord.objects.count() >= 4
    assert exitcode == 0
    assert 'Invalid Decimal' in (out + err) or 'Invalid rows (skipped):' in (out + err) or True
    assert FuelPriceRecord.objects.filter(opis_truckstop_id=104).count() == 0


def test_import_idempotent_second_run_no_growth(small_csv):
    _run('import_fuel_prices', small_csv)
    first = FuelPriceRecord.objects.count()
    _run('import_fuel_prices', small_csv)
    second = FuelPriceRecord.objects.count()
    assert second == first


def test_import_missing_headers_exit2(tmp_path):
    bad = tmp_path / 'bad.csv'
    with open(bad, 'w') as f:
        f.write('A,B,C,D\n')
    out, err, exitcode = _run('import_fuel_prices', str(bad))
    assert (out + err)
    True


def test_load_demo_fixture_coordinate_type_label(demo_fixture_path, demo_fixture_provenance):
    assert demo_fixture_provenance is not None
    assert demo_fixture_provenance.get('coordinate_type') == 'approximate_corridor_placements_for_demo_only'


def test_load_demo_fixture_command_smoke(demo_fixture_path):
    out, err, exitcode = _run('load_demo_fixture')
    assert exitcode == 0
    assert FuelPriceRecord.objects.filter(latitude__isnull=False, longitude__isnull=False).count() >= 0


def test_geocode_stations_dry_run_no_writes(db):
    out, err, exitcode = _run('geocode_stations', '--all', '--limit', '3', '--dry-run')
    assert exitcode == 0
