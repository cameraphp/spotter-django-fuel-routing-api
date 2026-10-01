from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError

from routing.models import FuelPriceRecord
from routing.services.geocoding import CachedGeocoder, GeocodeResult, NominatimGeocoder

_WS_RE = re.compile(r'\s+')


def _norm(value: str | None) -> str:
    if value is None:
        return ''
    return _WS_RE.sub(' ', value.strip())


def _natural_key_hash(truckstop_name, address, city, state) -> str:
    parts = [
        _norm(truckstop_name).upper(),
        _norm(address).upper(),
        _norm(city).upper(),
        _norm(state).upper(),
    ]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


def _build_query(station: FuelPriceRecord) -> str:
    parts = []
    if station.address:
        parts.append(station.address)
    if station.city:
        parts.append(station.city)
    if station.state:
        parts.append(station.state)
    parts.append('USA')
    return ', '.join(p for p in parts if p)


class Command(BaseCommand):
    help = (
        'Geocode fuel station records using Nominatim. Optional bulk preparation '
        'tool; subject to provider usage policies. Never runs at request time.'
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--all', action='store_true', help='Geocode all rows missing coordinates.')
        group.add_argument('--csv', type=str, help='Path to CSV (OPIS Truckstop ID / Name / Address / City / State).')
        parser.add_argument('--limit', type=int, default=None, help='Max rows to attempt geocoding on.')
        parser.add_argument('--pacing-seconds', type=float, default=1.0, help='Min seconds between external Nominatim calls (default 1.0).')
        parser.add_argument('--dry-run', action='store_true', help='No HTTP, no writes; print planned counts only.')

    def handle(self, *args: object, **options: object) -> str | None:
        dry_run: bool = bool(options['dry_run'])
        pacing: float = float(options['pacing_seconds'])
        limit: int | None = options['limit']

        stations: Iterable[FuelPriceRecord]
        if options.get('csv'):
            csv_path = str(options['csv'])
            if not os.path.isfile(csv_path):
                raise CommandError(f'CSV file not found: {csv_path!r}')
            csv_keys: set[str] = set()
            with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        int(_norm(str(row.get('OPIS Truckstop ID', ''))))
                    except (TypeError, ValueError):
                        continue
                    natural_key_hash = _natural_key_hash(
                        row.get('Truckstop Name'), row.get('Address'),
                        row.get('City'), row.get('State'),
                    )
                    csv_keys.add(natural_key_hash)
            stations = list(
                FuelPriceRecord.objects.filter(
                    natural_key_hash__in=list(csv_keys),
                    latitude__isnull=True,
                    longitude__isnull=True,
                ).order_by('id')
            )
        else:
            stations = list(
                FuelPriceRecord.objects.filter(
                    latitude__isnull=True, longitude__isnull=True
                ).order_by('id')
            )
        stations = list(stations)
        if limit is not None:
            stations = stations[:max(0, int(limit))]

        total = len(stations)
        self.stdout.write(f'Stations to geocode: {total}')
        self.stdout.write(f'Pacing (seconds between external calls): {pacing}')
        self.stdout.write(f'Dry run: {dry_run}')
        self.stdout.write(
            self.style.WARNING(
                'NOTE: Bulk Nominatim geocoding may take a long time and is '
                'subject to provider (OSM Nominatim) usage policies.'
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'DRY-RUN: would attempt {total} stations. No HTTP or writes performed.'
                )
            )
            return None

        inner = NominatimGeocoder(pacing_seconds=max(0.0, pacing))
        geocoder = CachedGeocoder(inner)

        attempted = 0
        resolved = 0
        unresolved = 0
        errors = 0
        updated = 0

        try:
            for station in stations:
                attempted += 1
                query = _build_query(station)
                try:
                    result: GeocodeResult = geocoder.geocode(query, country_codes='us')
                except Exception as exc:
                    errors += 1
                    self.stderr.write(f'  line station.id={station.id}: {exc}')
                    continue
                if result.latitude is None or result.longitude is None:
                    unresolved += 1
                    continue
                station.latitude = result.latitude
                station.longitude = result.longitude
                station.save(update_fields=['latitude', 'longitude'])
                resolved += 1
                updated += 1
        finally:
            inner.close()

        self.stdout.write(self.style.SUCCESS(f'Attempted:    {attempted}'))
        self.stdout.write(self.style.SUCCESS(f'Resolved OK:  {resolved}'))
        self.stdout.write(f'Unresolved:   {unresolved}')
        self.stdout.write(self.style.ERROR(f'Provider errors: {errors}'))
        self.stdout.write(f'DB rows updated: {updated}')
        return None
