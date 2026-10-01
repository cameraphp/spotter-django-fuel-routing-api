from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from routing.models import FuelPriceRecord

REQUIRED_HEADERS: list[str] = [
    'OPIS Truckstop ID',
    'Truckstop Name',
    'Address',
    'City',
    'State',
    'Rack ID',
    'Retail Price',
]

_WS_RE = re.compile(r'\s+')


def _norm(value: str | None) -> str:
    if value is None:
        return ''
    return _WS_RE.sub(' ', value.strip())


def _natural_key(
    truckstop_name: str,
    address: str,
    city: str,
    state: str,
) -> str:
    parts = [
        _norm(truckstop_name).upper(),
        _norm(address).upper(),
        _norm(city).upper(),
        _norm(state).upper(),
    ]
    joined = '|'.join(parts)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()


class Command(BaseCommand):
    help = 'Import fuel-price records from the provided CSV.'

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument('csv_path', type=str, help='Path to the CSV file.')

    def handle(self, *args: object, **options: object) -> str | None:
        csv_path = str(options['csv_path'])
        if not os.path.isfile(csv_path):
            raise CommandError(f'CSV file not found: {csv_path!r}')

        source_file = os.path.basename(csv_path)
        total = 0
        inserted = 0
        skipped_dupes = 0
        invalid_rows: list[tuple[int, str, str]] = []

        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            missing = [h for h in REQUIRED_HEADERS if h not in headers]
            if missing:
                self.stderr.write(
                    self.style.ERROR(
                        f'ERROR: CSV missing required headers: {missing!r}'
                    )
                )
                sys.exit(2)

            for line_idx, row in enumerate(reader, start=2):
                total += 1
                price_raw = row.get('Retail Price', '') or ''
                price_stripped = price_raw.strip()
                try:
                    retail_price = Decimal(price_stripped)
                except (InvalidOperation, ValueError, TypeError) as exc:
                    invalid_rows.append(
                        (line_idx, repr(price_raw), f'Invalid Decimal parse: {exc}')
                    )
                    continue
                if retail_price < 0:
                    invalid_rows.append(
                        (line_idx, repr(price_raw), 'Negative Retail Price')
                    )
                    continue
                try:
                    opis_id = int(_norm(str(row.get('OPIS Truckstop ID', ''))))
                except (TypeError, ValueError) as exc:
                    invalid_rows.append(
                        (line_idx, repr(row.get('OPIS Truckstop ID')), f'Bad OPIS ID: {exc}')
                    )
                    continue
                truckstop_name = _norm(row.get('Truckstop Name'))
                address = _norm(row.get('Address'))
                city = _norm(row.get('City'))
                state = _norm(row.get('State'))
                rack_id = _norm(row.get('Rack ID'))
                natural_key_hash = _natural_key(truckstop_name, address, city, state)

                try:
                    FuelPriceRecord.objects.create(
                        opis_truckstop_id=opis_id,
                        truckstop_name=truckstop_name,
                        address=address,
                        city=city,
                        state=state,
                        rack_id=rack_id,
                        retail_price=retail_price,
                        natural_key_hash=natural_key_hash,
                        source_row_id=line_idx,
                        source_file=source_file,
                        latitude=None,
                        longitude=None,
                    )
                    inserted += 1
                except Exception:
                    skipped_dupes += 1

        self.stdout.write(self.style.SUCCESS(f'Source file: {source_file}'))
        self.stdout.write(f'Total rows read:            {total}')
        self.stdout.write(self.style.SUCCESS(f'Successfully inserted:    {inserted}'))
        self.stdout.write(f'Skipped (duplicates):      {skipped_dupes}')
        self.stdout.write(
            self.style.ERROR(f'Invalid rows (skipped):    {len(invalid_rows)}')
        )
        for line_no, raw, reason in invalid_rows[:50]:
            self.stdout.write(
                f'  line {line_no}: price={raw} reason={reason}'
            )
        if len(invalid_rows) > 50:
            self.stdout.write(f'  ... {len(invalid_rows) - 50} more invalid rows omitted.')
        return None
