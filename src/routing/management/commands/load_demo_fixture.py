from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from routing.models import FuelPriceRecord

FIXTURE_FILENAME = 'demo_stations_with_approximate_coordinates.json'
EXPECTED_COORDINATE_TYPE = 'approximate_corridor_placements_for_demo_only'


class Command(BaseCommand):
    help = (
        'Load the demo fixture with honestly-labeled approximate corridor '
        'station coordinates. Sufficient for the assessment Loom example; '
        'coordinates are NOT genuine Nominatim geocodes.'
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--fixture-path',
            type=str,
            default=None,
            help='Override path to the fixture JSON file.',
        )

    def handle(self, *args: object, **options: object) -> str | None:
        fixture_path = options.get('fixture_path')
        if fixture_path is None:
            commands_dir = os.path.dirname(os.path.abspath(__file__))
            management_dir = os.path.dirname(commands_dir)
            routing_dir = os.path.dirname(management_dir)
            fixture_dir = os.path.join(routing_dir, 'fixtures')
            fixture_path = os.path.join(fixture_dir, FIXTURE_FILENAME)
        if not os.path.isfile(fixture_path):
            raise CommandError(f'Fixture not found: {fixture_path!r}')

        with open(fixture_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)

        provenance = payload.get('_provenance') or {}
        coordinate_type = provenance.get('coordinate_type')
        if coordinate_type != EXPECTED_COORDINATE_TYPE:
            raise CommandError(
                'Fixture _provenance.coordinate_type mismatch: '
                f'expected {EXPECTED_COORDINATE_TYPE!r}, got {coordinate_type!r}. '
                'Refusing to load unlabeled coordinates.'
            )

        self.stdout.write(
            self.style.WARNING(
                '==============================================================\n'
                'DEMO FIXTURE COORDINATE PROVENANCE NOTICE\n'
                '==============================================================\n'
                'Fixture: ' + str(provenance.get('fixture_name', FIXTURE_FILENAME)) + '\n'
                'Coordinate type: ' + str(coordinate_type) + '\n'
                'Station count: ' + str(provenance.get('station_count', '?')) + '\n'
                'Description:\n  '
                + str(provenance.get('description', '(none)')).replace('\n', '\n  ')
                + '\n--------------------------------------------------------------\n'
                'These approximate coordinates are for ASSESSMENT DEMO USE ONLY. '
                'They are NOT genuine Nominatim address-level geocodes and they '
                'are NOT city centroids. For production-quality coordinates use '
                'the `geocode_stations` management command.\n'
                '=============================================================='
            )
        )

        records = payload.get('records') or []
        source_file = os.path.basename(fixture_path)
        inserted = 0
        updated_coords = 0
        skipped = 0
        invalid = 0
        for idx, row in enumerate(records):
            nkh = row.get('natural_key_hash') or ''
            if not nkh:
                invalid += 1
                continue
            lat_str = str(row.get('latitude') or '').strip()
            lon_str = str(row.get('longitude') or '').strip()
            if not lat_str or not lon_str:
                invalid += 1
                continue
            try:
                latitude = Decimal(lat_str)
                longitude = Decimal(lon_str)
            except (InvalidOperation, ValueError, TypeError):
                invalid += 1
                continue
            try:
                retail_price = Decimal(str(row.get('retail_price', '0')).strip())
            except (InvalidOperation, ValueError, TypeError):
                invalid += 1
                continue
            existing = FuelPriceRecord.objects.filter(
                natural_key_hash=nkh,
            ).order_by('retail_price').first()
            if existing is None:
                try:
                    FuelPriceRecord.objects.create(
                        opis_truckstop_id=int(row.get('opis_truckstop_id') or 0),
                        truckstop_name=str(row.get('truckstop_name') or ''),
                        address=str(row.get('address') or ''),
                        city=str(row.get('city') or ''),
                        state=str(row.get('state') or ''),
                        rack_id=str(row.get('rack_id') or ''),
                        retail_price=retail_price,
                        natural_key_hash=nkh,
                        source_row_id=idx + 2,
                        source_file=source_file,
                        latitude=latitude,
                        longitude=longitude,
                    )
                    inserted += 1
                except Exception:
                    skipped += 1
            else:
                changed = False
                if existing.latitude is None:
                    existing.latitude = latitude
                    changed = True
                if existing.longitude is None:
                    existing.longitude = longitude
                    changed = True
                if changed:
                    existing.save(update_fields=['latitude', 'longitude'])
                    updated_coords += 1
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(f'Fixture: {os.path.basename(fixture_path)}'))
        self.stdout.write(f'  records parsed:         {len(records)}')
        self.stdout.write(self.style.SUCCESS(f'  newly inserted:         {inserted}'))
        self.stdout.write(self.style.SUCCESS(f'  coordinates updated:    {updated_coords}'))
        self.stdout.write(f'  skipped (existing):     {skipped}')
        self.stdout.write(self.style.ERROR(f'  invalid rows:           {invalid}'))
        total_with_coords = FuelPriceRecord.objects.filter(
            latitude__isnull=False, longitude__isnull=False
        ).count()
        self.stdout.write(
            self.style.SUCCESS(
                f'  FuelPriceRecord rows with coordinates (post-load): {total_with_coords}'
            )
        )
        return None
