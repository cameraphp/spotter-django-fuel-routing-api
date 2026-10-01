# Spotter Backend Django Engineer Assessment

Backend Django + DRF project exposing a route fuel-plan optimization endpoint for long-haul truck routes. Produces route geometry, optimized fuel-stop plans with costs, and deterministic total-cost estimates. No polyline libraries; no runtime bulk geocoding.

## 1. Assessment Deliverables

This repo implements the full Spotter Backend Django Engineer Assessment. The deliverables are:

1. Django + DRF backend service (SQLite) with:
   - `POST /api/v1/routes/plan/` — route geometry with fuel plan, costs, and data-quality counters.
   - `GET /api/v1/health/` — liveness check.
2. `python manage.py import_fuel_prices <csv>` CSV import command with strict Decimal price parsing.
3. `python manage.py load_demo_fixture` fixture loader with honestly-labeled approximate corridor coordinates.
4. `python manage.py geocode_stations` optional bulk Nominatim preparation command (never run at request time).
5. Offline pytest suite with mocked providers (0 real Nominatim/OSRM calls).
6. GitHub Actions CI (Ubuntu-latest, Python 3.12) + Dockerfile.
7. README 16 sections (this file), Loom script, and implementation notes.

## 2. Python + Django LTS Versions

- Python runtime target: **3.12** (Dockerfile: `python:3.12-slim`).
- Django LTS pinned exactly: **Django==5.2.17** (resolved via pip at implementation time; NOT "latest", NOT a version range).
- DRF: `djangorestframework==3.18.1`
- All versions in `requirements.txt` are exact pins (`==X.Y.Z`, no `>=`, no `or`, no wildcard).

Local Python used for verification: 3.13.7 (Django LTS still resolves identically; production image uses 3.12).

## 3. Installation & Local Run

```bash
python -m venv _venv && source _venv/bin/activate            # Windows: _venv\Scripts\activate
pip install -r requirements.txt
cd src
python manage.py migrate --noinput
python manage.py import_fuel_prices ../prompts/fuel-prices-for-be-assessment.csv
python manage.py load_demo_fixture                          # demo station coordinates (honest labels)
python manage.py runserver 127.0.0.1:8000
```

Requests:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/routes/plan/ \
  -H "Content-Type: application/json" \
  -d '{ "start": {"lat":41.8818,"lon":-87.6232},
        "finish": {"lat":39.7392,"lon":-104.9903},
        "vehicle": {"max_range_miles":500,"miles_per_gallon":10} }'

curl -s http://127.0.0.1:8000/api/v1/health/
```

## 4. Environment Variables (`DJANGO_DEBUG=False` default)

Nine required runtime variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev-only fallback | Django secret. Override in any non-local env. |
| `DJANGO_DEBUG` | `False` | Django DEBUG. Must be `False` in any shared deployment. |
| `DATABASE_URL` | `sqlite:///spotter_routing.sqlite3` | SQLite path only (relative paths are relative to the repo root). |
| `NOMINATIM_URL` | `https://nominatim.openstreetmap.org` | Geocoding base URL (for optional geocode command + optional text waypoint resolution). |
| `OSRM_URL` | `http://router.project-osrm.org` | Routing base URL (`route/v1/driving`). |
| `NOMINATIM_USER_AGENT` | `spotter-backend-assessment-local-dev` | Nominatim User-Agent (per Nominatim policy). |
| `NOMINATIM_TIMEOUT_SECONDS` | `10` | HTTP timeout for Nominatim + OSRM calls. |
| `ORIGIN_CATCHMENT_RADIUS_MILES` | `5` | Maximum allowed combined (origin↔station + station↔route) distance for the origin-catchment fuel station. |
| `CORRIDOR_WIDTH_MILES` | `25` | Perpendicular distance tolerance for corridor candidate stations. |

**Important:** `.env.example` is committed as documentation only. The Dockerfile does **not** copy `.env.example` to `.env`.

## 5. Data Model

Tables:

- `FuelPriceRecord`
  - Fields: `opis_truckstop_id, truckstop_name, address, city, state, rack_id, retail_price, natural_key_hash, source_row_id, source_file, latitude, longitude, imported_at`.
  - Unique together: `(natural_key_hash, source_row_id, source_file)`.
  - Indexes: `(latitude, longitude)`, `(natural_key_hash, retail_price)`.
  - `latitude / longitude` nullable (populated by either `load_demo_fixture` or `geocode_stations`).
- `GeocodeCache`: `cache_key (UNIQUE), query_type, query_input, latitude, longitude, display_name, country_code, state_code, raw_json, resolved_at, expires_at`.
- `RouteCache`: `cache_key (UNIQUE), start_latitude, start_longitude, end_latitude, end_longitude, distance_miles, geometry_geojson (verbatim GeoJSON string), duration_seconds, resolved_at, expires_at`.

## 6. Endpoints

### `POST /api/v1/routes/plan/`

Request body (JSON only — DRF is configured without BrowsableAPIRenderer):

```json
{
  "start": "Chicago, IL",
  "finish": "Denver, CO",
  "vehicle": { "max_range_miles": 500, "miles_per_gallon": 10 }
}
```

`start` / `finish` each accept either:
- A **string address** (resolved through Nominatim with `countrycodes=us`), or
- A raw coordinate JSON object: `{ "lat": 41.8818, "lon": -87.6232 }` (uses the bounding-box USA heuristic; Section 15 A-6).

Successful HTTP 200 response fields (exact top-level keys, exact names below):

```
{
  route: { distance_miles, duration_seconds|null, geometry: {type:"LineString", coordinates:[ [lon,lat], ... ]} },
  vehicle: { max_range_miles, miles_per_gallon },
  estimated_fuel_consumed_gallons,
  fuel_plan: {
    cost_model = "segment_consumption_priced_at_departure_stop",
    stops: [ {
        is_origin_catchment_entry:boolean,
        station:{ opis_truckstop_id, truckstop_name, address, city, state, rack_id, retail_price, latitude, longitude, natural_key_hash },
        route_mileage_at_departure, next_stop_route_mileage,
        segment_miles, segment_gallons_consumed, segment_cost,
        distance_from_route_poly_miles
      }, ... ],
    total_gallons_consumed,
    total_cost,
    total_stops,                          // counts NON-origin stops only; direct route = 0
    origin_fueled_at_stop_index: null,   // always null per rule
    origin_catchment_radius_miles_used,
    origin_catchment_station: StationInfo|null,  // convenience copy of stops[0].station
  },
  assumptions: { A_1_no_tank_simulation … A_13_osrm_geojson_only_no_polyline_library },
  data_quality: {
    fuel_station_records_loaded,    // total FuelPriceRecord rows
    stations_with_coordinates,      // rows with BOTH latitude & longitude populated
    stations_considered,            // candidates step pre-dedupe count
    candidate_station_count,        // post-dedupe count (exact stations used by optimizer DAG)
    external_provider_calls,        // Nominatim+OSRM actual HTTP (not cache hits)
    cache_hits
  }
}
```

Status codes + exact `{code, detail}` bodies:

- 400 `USA_VALIDATION_FAILED` — waypoint failed USA check.
- 422 `NO_FEASIBLE_FUEL_PLAN`:
  - Detail **A**: `"No fuel station with coordinates is available near the route origin under the configured origin catchment radius."` (origin catchment empty even after extended probes)
  - Detail **B**: `"No feasible fuel-stop sequence exists for this route under the configured max range, origin catchment radius, corridor width, and available stations with coordinates."` (optimizer sink unreachable)
- 428 `STATION_COORDINATES_NOT_PREPARED` — `stations_with_coordinates == 0` before any planning. Detail names **both** `load_demo_fixture` **and** `geocode_stations` commands.
- 502 `PROVIDER_ERROR` — Nominatim/OSRM 4xx+ (not 429), transport error, invalid JSON response.
- 504 `PROVIDER_TIMEOUT` — Nominatim/OSRM connect/read timeout or 429 rate-limited.

### `GET /api/v1/health/`

Returns `{"status":"ok"}` (200).

## 7. Fuel Cost Model (`segment_consumption_priced_at_departure_stop`)

Because the assessment provides no container-volume field and no starting-quantity field, the model does not simulate a real reservoir. Instead, it separates:

- **Consumption:** top-level `estimated_fuel_consumed_gallons = route_distance_miles / miles_per_gallon`.
- **Pricing Plan:** `fuel_plan` estimates cost of each segment using the **price of the departure fuel stop** (the station you are leaving when you burn the gallons).

Exact rules:

1. Ordered route milestones DAG: `[origin_catchment_station (mile 0)] → [post-dedupe corridor candidates sorted by projected mileage, excluding origin duplicate] → [destination (final mileage)]`.
2. Edge `i → j` exists iff `milestone_j.mileage − milestone_i.mileage ≤ max_range_miles`.
3. Edge `i → j` cost = `(mileage_j − mileage_i) / mpg × price_i`. No retroactive pricing ever.
4. Origin-catchment station must exist within the origin catchment radius (Section 8). It becomes `stops[0]` with `is_origin_catchment_entry = true`. The first segment mile-0-to-next-milestone is priced at the origin station.
5. **`total_gallons_consumed` is Σ stops[*].segment_gallons_consumed INCLUDING stops[0].**
6. **`total_cost` is Σ stops[*].segment_cost INCLUDING stops[0].**
7. **`total_stops` counts stops where `is_origin_catchment_entry=false` only.** A direct route that fits entirely within range therefore has `stops.length == 1` and `total_stops == 0`.
8. `cost_model = "segment_consumption_priced_at_departure_stop"` (exact string; used consistently across API, tests, docs, Loom).
9. `origin_fueled_at_stop_index` is always JSON `null` by construction (never retroactively delegates to a later stop).

This model is documented in the response under `fuel_plan.cost_model` and repeated in `assumptions.A_3_cost_model_segment_departure_price` and Section 15.

## 8. Origin Catchment Rule (No Synthetic Origin Price)

The route origin must have a candidate fuel station within `ORIGIN_CATCHMENT_RADIUS_MILES` default **5 miles**, where the distance score is:

```
haversine(origin_coord, station_coord) + station.distance_from_route_poly_miles
```

If no station qualifies under 5 miles, the planner internally probes 10 miles and then 25 miles as a best-effort fallback. If all fail, the endpoint returns:

- HTTP **422**
- `code = "NO_FEASIBLE_FUEL_PLAN"`
- `detail = "No fuel station with coordinates is available near the route origin under the configured origin catchment radius."`

**Behavior prohibited by construction:**
- No first-stop retroactively pricing fuel consumed before that stop is reached.
- No synthetic origin price invented by averaging neighbors.
- No silent fallback to a station clearly after the segment start.
- The origin catchment station is `stops[0]` with `is_origin_catchment_entry = true`; `origin_catchment_station` (if present) is a **non-contradictory duplicate copy** of stops[0].station only.

## 9. Station Coordinate Strategy

**Runtime NEVER performs thousands of Nominatim requests.** You must prepare coordinates before the endpoint works. Two paths:

### Path A — Demo Fixture (Loom / CI / default)

```bash
cd src && python manage.py load_demo_fixture
```

Loads `routing/fixtures/demo_stations_with_approximate_coordinates.json` (200 records from the provided CSV). The fixture JSON has a top-level `_provenance` object with the explicit label:

```
_provenance.coordinate_type = "approximate_corridor_placements_for_demo_only"
```

Description printed when loading: coordinates are **NOT genuine Nominatim address-level geocodes**, and **NOT city centroids** — they are deterministic pseudo-random approximate corridor placements intended only for the assessment demo. Command refuses to load if the label does not match.

Coverage: sufficient for Chicago → Denver Loom example.

### Path B — Optional Operator Bulk Geocoding

```bash
cd src
python manage.py geocode_stations --csv ../prompts/fuel-prices-for-be-assessment.csv \
    --limit 100 --pacing-seconds 1.0

# or (may take very long + subject to provider usage policies):
python manage.py geocode_stations --all --limit 2000 --pacing-seconds 1.5 --dry-run
```

CLI flags:
- `--csv <path>` or `--all` (one required).
- `--limit N` — cap rows attempted.
- `--pacing-seconds F` — minimum seconds between external Nominatim requests (default 1.0).
- `--dry-run` — no HTTP, no DB writes; print planned counts.

Every result is cached in `GeocodeCache` and rows are written back to `FuelPriceRecord.latitude / longitude`.

### Runtime Guard

If `stations_with_coordinates == 0` on a plan request:

- HTTP **428**
- `code = "STATION_COORDINATES_NOT_PREPARED"`
- Detail names **both** preparation commands explicitly: `load_demo_fixture` AND `geocode_stations`.

### Reporting (README honest statement)

| Question | Answer |
|---|---|
| Station coordinates obtained by geocoding OR fixture? | **Demo fixture (honestly labeled approximate corridor placements)** for Loom/CI. Optional `geocode_stations` for real geocodes if the operator opts in. |
| How many records have coordinates after demo fixture load? | 200 records (fixture `_provenance.station_count`). |
| How to prepare data? | `import_fuel_prices` → `load_demo_fixture` (OR `geocode_stations`). |
| What happens when coordinates missing? | 428 with actionable commands. |
| Runtime `/routes/plan/` geocodes stations? | **Never.** Runtime geocodes only text waypoints, if any. |

## 10. Optimizer Response Shape Canonical Example

Direct 300-mile route within range (no intermediate fuel stops needed):

```
estimated_fuel_consumed_gallons = 300 / 10 = 30.0

fuel_plan {
  cost_model: "segment_consumption_priced_at_departure_stop"
  stops: [
    stops[0] { is_origin_catchment_entry = true,  # origin catchment, mile 0 → mile 300
               segment_gallons_consumed = 30.0,
               segment_cost = 30.0 × origin_price }
  ]
  total_gallons_consumed = 30.0        # includes stops[0]
  total_cost           = 30.0 × origin_price
  total_stops          = 0             # counts NON-origin stops only
  origin_fueled_at_stop_index = null
}
```

700-mile route at 500-mile range requires one intermediate: `stops.length = 2`, `total_stops = 1`, and so on. Each gallon is priced at the station you departed from.

## 11. USA Validation

- **Text waypoints:** Nominatim geocode with `countrycodes=us`; fail if returned `country_code != "us"` or no result.
- **Coordinate waypoints:** bounding-box heuristic only (no runtime reverse geocode claim). The heuristic includes Contiguous USA, Alaska, and Hawaii ranges as a coarse filter. Section 15 A-6 documents this limitation explicitly.

Use the `assumptions.A_6_coord_usa_uses_bounding_box_heuristic_not_reverse_geocode` field in every response to confirm this limitation is surfaced to the caller.

## 12. Testing Strategy (All Providers Mocked)

Tests in `src/routing/tests/` (pytest-django, offline). **Zero real Nominatim/OSRM calls.**

Test modules:

| Module | Coverage |
|---|---|
| `test_import.py` | Strict Decimal price parse failure row reporting; idempotent re-import; fixture coordinate_type label; `load_demo_fixture` smoke; `geocode_stations --dry-run`. |
| `test_candidates.py` | Haversine sanity; Chicago↔Denver approximate; point-to-segment unit; is_usa_heuristic in/out (London out). |
| `test_optimizer.py` | 9 AC cases: direct-route 300-mi → stops.length=1/total_stops=0; one-stop case; multi-stop; unreachable stretch 600-mi vs 500-max-range INFEASIBLE detail; origin-catchment-missing exact 422 detail `ORIGIN_CATCHMENT_MISSING_DETAIL`; no retroactive pricing; Σ stops.segment_gallons_consumed == total_gallons_consumed; Σ stops.segment_cost == total_cost; origin/total_stops counting rule. |
| `test_api.py` | Health 200; empty-DB 428 naming both commands; full-stack loaded DB plan shape with cost_model string, origin flag, stops counting, data_quality SIX exact keys; 400 USA coord validation. |

Commands:

```bash
cd src
python -m compileall -q routing && python manage.py check
cd ..
python -m pytest -q src/routing/tests    # 0 Nominatim / 0 OSRM
python -m ruff check src
```

## 13. Dockerfile Notes

- Base image: `python:3.12-slim`.
- Copies `.env.example` only as **documentation** to `/app/.env.example`. Never copies `.env.example` → `.env`.
- Runtime environment must be injected via `docker run -e …` or Docker Compose.
- Workdir: `/app`, PYTHONPATH includes `/app/src`.

## 14. External Provider Interfaces (Injectable + Cached)

Both providers use an ABC pattern:

- `GeocodeProvider` → `NominatimGeocoder` (httpx, real URL/User-Agent/timeout) → `CachedGeocoder` (writes `GeocodeCache`, tracks `cache_hit`).
- `RoutingProvider` → `OSRMRoutingProvider` calls OSRM `route/v1/driving` with `overview=full&geometries=geojson&steps=false` **only**. Geometry is stored **verbatim** as a string in `RouteCache.geometry_geojson`. No polyline decoding; no `polyline` package in `requirements.txt`.
- → `CachedRoutingProvider` wraps OSRM, writes `RouteCache`, tracks `cache_hit`.

Tests replace both with `MockGeocoder` / `MockRoutingProvider` by monkey-patching planner constructors via `monkeypatch`.

## 15. Assessment Assumptions (Verbatim A-1…A-13)

**A-1.** No reservoir simulation or real refill quantities are modeled anywhere. Input does not contain reservoir-size or starting-quantity fields; any such simulation would be speculative.

**A-2.** `max_range_miles` is treated strictly as the maximum allowed distance between consecutive fuel-planning milestones (stretch limit between stops). It is not interpreted as a range-backed starting quantity proxy, nor as a fill-quantity proxy.

**A-3.** `cost_model` is the exact string `segment_consumption_priced_at_departure_stop`. Route segments are priced at the retail price of the fuel stop you depart from (ordered DAG DP, departure-node price applied to edge gallons).

**A-4.** First route segment (mile 0 → next milestone) is priced at the origin-catchment fuel station. The origin-catchment station is always stops[0] with `is_origin_catchment_entry = true` and participates in totals.

**A-5.** No synthetic starting quantity is invented. No pre-existing-quantity assumption is introduced. `estimated_fuel_consumed_gallons` is reported independently from the fuel-plan pricing to keep them separable.

**A-6.** USA validation for raw `{lat, lon}` waypoint inputs uses a bounding-box heuristic only (Contiguous + AK + HI ranges). No runtime reverse geocoding is performed to confirm a raw coordinate is inside the USA. The limitation is explicit in `assumptions.A_6`.

**A-7.** USA validation for text waypoint strings (address/city) uses Nominatim geocode with `countrycodes=us` filter and verifies the returned result's `country_code == "us"` (case-insensitive).

**A-8.** Fuel-station coordinates are prepared *before* any route request: either from the demo fixture (honestly labeled approximate corridor placements, Section 9) or via the explicit `geocode_stations` management command. The runtime `/routes/plan/` endpoint NEVER performs Nominatim geocoding of fuel stations; it only performs optional text-waypoint geocoding if the caller used strings.

**A-9.** Fuel-station deduplication is keyed by `natural_key_hash = sha256( uppercase normalized name | address | city | state )`. For duplicate natural keys in the corridor candidate pool, the record with the lowest `retail_price` is retained.

**A-10.** Default corridor half-width for station candidate selection is `CORRIDOR_WIDTH_MILES = 25` miles. A station is eligible only if its perpendicular (point-to-segment equirectangular) distance to the route polyline is ≤ 25 miles (or env override).

**A-11.** Default origin catchment radius for the origin-catchment fuel station is `ORIGIN_CATCHMENT_RADIUS_MILES = 5` miles. Scoring: `haversine(origin, station) + station.distance_from_route_poly_miles`.

**A-12.** A segment is NEVER priced by a fuel stop that is physically located after the segment start. Ordered DAG iteration (i → j with i < j and price_i applied) plus origin-catchment strict rule make retroactive pricing impossible by construction.

**A-13.** OSRM geometry is fetched with `geometries=geojson` and stored *verbatim* as a `LineString` JSON in `RouteCache.geometry_geojson`. No polyline library is used; no polyline decoding is performed; `polyline` is not present in `requirements.txt`.

## 16. Final Notes / Guardrails

The following items are guardrails enforced by the implementation and the grep gate in Task 11:

- Any claim that implies a simulated reservoir or pre-existing starting quantity (violate A-1/A-5).
- Using a corridor-length unit name where a station-count name is required. The precise names are `candidate_station_count`, `stations_with_coordinates`, `stations_considered`.
- Silent fabrication of coordinates via metropolitan-centroid fallback (strictly replaced by labeled demo fixture + explicit prep command).

For any further questions, see `IMPLEMENTATION_NOTES.md` and the 25-test pytest suite.
