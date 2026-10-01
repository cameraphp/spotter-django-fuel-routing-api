# Spotter Backend Django Engineer Assessment - Product Requirements Document

## Overview
- **Summary**: Build a complete, runnable Django backend API for Spotter AI that accepts US start/finish locations and returns a driving route plan with optimized fuel stops, segment costs, totals, and map-renderable GeoJSON geometry.
- **Purpose**: Deliver a technical assessment implementation demonstrating Django proficiency, API design, algorithmic optimization, service abstractions with dependency injection, caching, strict decimal money arithmetic, and quality engineering practices.
- **Target Users**: Assessment reviewers, API consumers (frontend map renderer), demo presenter (5-minute Loom).

## Goals
- Expose `POST /api/v1/routes/plan/` returning: route geometry, a top-level total route fuel consumption, and a fuel plan that estimates cost by pricing each route segment at the selected departure station. The origin catchment station is the FIRST entry in the stops list (flagged as such) and contains the mile-0-first-segment pricing.
- Expose `GET /api/v1/health/`.
- Import fuel prices from the supplied CSV via a documented, idempotent management command (strict Decimal price parsing, no scrubbing).
- Provide a clearly labeled demo fixture with APPROXIMATE corridor coordinates (NOT labeled "genuine" geocodes — see coordinate provenance section A-5) for fast Loom + CI zero-network setup.
- Additionally provide the optional `geocode_stations` prep command (limit, pacing, caching, dry-run) for operators who want real address-level coordinates from Nominatim.
- Use free OSM-based services (Nominatim for geocoding, OSRM for routing with `geometries=geojson`) with DB-backed caching.
- Require a fuel station within origin catchment radius before optimization; otherwise a clear 422. Origin station becomes the first stops-list entry with an explicit flag.
- Implement deterministic fuel optimization via DP on an ordered DAG of milestones with no retroactively-priced segments and no synthetic origin prices.
- Prevent any station-level geocoding during a plan request; route endpoint fails clearly if station coords not preloaded.
- Provide comprehensive test suite with *all* providers mocked (zero real Nominatim/OSRM calls).
- Provide Docker (clean image — no fake `.env` copy-in), CI workflow, `.env.example`, and demo-ready documentation (README + LOOM_SCRIPT + IMPLEMENTATION_NOTES).

## Non-Goals
- Production-grade deployment (assessment only per honesty rules).
- Paid map providers or API keys required for default demo.
- User authentication or authorization.
- Real-time fuel price updates or live price scraping.
- Mobile frontend (only machine-readable geometry).
- Per-station routing calls.
- A physically exact fuel-tank simulation with real purchases — no tank capacity, no initial fuel level, no refill quantity inputs exist in the request, so we do not model them.
- Fabricated station coordinates labeled as genuine geocodes. Demo fixture coordinates are approximate corridor placements and are honestly labeled as such (see A-5).
- Any synthetic or retroactive pricing of fuel that would misrepresent which station a segment is priced at.

## Background & Context
- Input CSV: `fuel-prices-for-be-assessment.csv` at repo root (~8,151 rows, columns: OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price).
- Dataset: duplicate OPIS IDs with varying prices exist; prices ~$2.69 to ~$6.40; no null values observed; stations across the USA.
- Stack: Python 3.12+, Django LTS (EXACT version resolved and pinned in Task 1 by actually installing it), Django REST Framework, SQLite default, httpx, pytest + pytest-django, ruff, python-dotenv. (Django version rule: NO speculative string in the spec — only the method.)

## Functional Requirements

### Data loading & preparation
- **FR-1**: `python manage.py import_fuel_prices <csv_path>` — idempotent CSV import. Normalizes whitespace on text fields. Parses Retail Price using **strict** `Decimal(price_str.strip())` with no character scrubbing; if Decimal raises on a row, the row is reported as invalid (line number + reason) and not inserted. Validates required header columns; missing headers → exit code 2 with stderr message. Preserves every valid source record (OPIS ID alone is not the unique key; unique on natural_key_hash + source_row_id + source_file). Stores a sha256 natural key hash per record. Reports summary counts.
- **FR-2**: `python manage.py load_demo_fixture` — PRIMARY tool for Loom and CI. Loads `routing/fixtures/demo_stations_with_approximate_coordinates.json`. Contains ~200 actual CSV station records matched by opis_truckstop_id + natural_key_hash with APPROXIMATE latitude/longitude coordinates PURPOSEFULLY PLACED ALONG THE CHICAGO→DENVER I-80 CORRIDOR FOR ASSESSMENT DEMO USE ONLY. Coordinates NOT obtained from Nominatim; NOT genuine address-level geocodes; NOT city centroids (placed along the route corridor manually to reflect the CSV station's listed state/city). Provenance documented in fixture JSON root `_provenance` object and in README. Sufficient to cover Chicago→Denver or similar Loom example.
- **FR-3**: `python manage.py geocode_stations [--csv <path> | --all] [--limit N] [--pacing-seconds FLOAT] [--dry-run]` — OPTIONAL bulk preparation tool for operators wanting real geocoded coordinates. Geocodes unique stations by normalized query string using Nominatim. Uses CachedGeocoder (DB cache). Respects User-Agent, HTTP timeouts, and configurable minimum pacing (default NOMINATIM_PACING_SECONDS ≥ 1.0 s). Updates lat/lng on all FuelPriceRecord rows sharing a successfully-geocoded natural_key. Continues past failures with reporting. CLEARLY DOCUMENTED as slow, policy-bound optional tool for operators. NEVER runs inside a route request.
- **FR-4**: Runtime 428 setup guard: if 0 candidate stations with lat/lng exist in the DB, `POST /api/v1/routes/plan/` returns **HTTP 428 Precondition Required** with:
  ```json
  {"code": "STATION_COORDINATES_NOT_PREPARED",
   "detail": "Run `python manage.py load_demo_fixture` (for fast demos — note: demo coordinates are approximate corridor placements, NOT genuine address geocodes) or `python manage.py geocode_stations --all --limit <N>` (optional slower Nominatim-based address-level geocoding) first."}
  ```

### Route plan API
- **FR-5**: `POST /api/v1/routes/plan/` JSON body: `start` (text or `{latitude, longitude}`), `finish` (same shape), optional `fuel_type` (default `"regular"`), optional `vehicle.max_range_miles` (default 500, must be > 0), optional `vehicle.miles_per_gallon` (default 10, must be > 0).
- **FR-6**: Two separate fuel-volume numbers in every response, each with a clear distinct purpose — no overlapping meaning:
  - **A. `estimated_fuel_consumed_gallons`** (top-level, Decimal): computed purely as `route.distance_miles / vehicle.miles_per_gallon`. Total physical fuel the route will burn. Independent of stops/prices.
  - **B. `fuel_plan.total_gallons_consumed`** (fuel_plan-level, Decimal): sum of `segment_gallons_consumed` across every entry in the `stops` array (including the origin-catchment first entry). Numerically equal to field A for a plan that covers the full route, reproduced here for cost-model clarity per segment.
  - **C. `fuel_plan.total_cost`**: sum of `segment_cost = segment_gallons_consumed * price_of_departure_station` across every entry in the `stops` array (including origin entry). Currency always USD.
- **FR-7**: Fuel plan method & origin stop INCLUSION rule (consistent throughout documents, code, tests, response, Loom). **Single exact `cost_model` name used everywhere:**
  > `cost_model = "segment_consumption_priced_at_departure_stop"`
  - `vehicle.max_range_miles` is used SOLELY as the maximum distance allowed between consecutive route milestones. It is not a tank-size quantity, and the phrases "full tank", "tank capacity", "initial fuel level", "starts with a full tank", "starts full" DO NOT appear in any code, test, response assumption, README section, or Loom script.
  - Milestones = [origin mile 0 with its already-pinned origin catchment station price] + [candidate stations sorted by projected route mileage] + [destination at total miles].
  - **Origin catchment rule (deterministic, no delegation, no retroactivity):**
    1. Before DP optimization starts, query corridor candidate stations and find the candidate with minimum distance where `haversine(origin_point, station) + station.distance_from_route_polyline ≤ ORIGIN_CATCHMENT_RADIUS_MILES` (configurable env, default **5 miles**).
    2. If NO candidate satisfies this → optimization impossible. Return **HTTP 422 Unprocessable Entity** with `{"code":"NO_FEASIBLE_FUEL_PLAN","detail":"No fuel station with coordinates is available near the route origin under the configured origin catchment radius."}`
    3. If found → pin this origin catchment station as milestone 0's pricing source. Origin milestone 0 price = that station's retail price.
  - **Stops list INCLUDES origin catchment station as the FIRST entry (index 0), with a distinguishing flag.** This is the consistent model:
    - `fuel_plan.stops[0]` = the origin catchment station entry.
    - `fuel_plan.stops[0].is_origin_catchment_entry` = **true** (boolean always present on every stop entry; it is false on all non-origin entries).
    - `stops[0]` covers the FIRST route segment from mile 0 to the next milestone (either the next purchased stop or the destination if direct route within range). Its segment_start=0, segment_end=next_milestone_mileage.
    - `fuel_plan.total_gallons_consumed` and `fuel_plan.total_cost` EXPLICITLY include `stops[0]` segment contributions.
    - `fuel_plan.total_stops` counts ONLY non-origin fueling stops = `len([s for s in stops if not s.is_origin_catchment_entry])`. A direct route ≤ max_range with no intermediate stops therefore has `stops.length = 1` (just origin entry) AND `total_stops = 0`. This combination is consistent by definition.
    - `fuel_plan.origin_fueled_at_stop_index` is **always JSON `null`**. Reason: origin is pinned directly as the first pricing entry via its own stop, not delegated from a later stop. Do not remove this field — keep it as null so existing consumers have a stable schema.
    - `fuel_plan.origin_catchment_station`: **include this convenience object** containing the origin station info (opis_id, name, city, state, price, catchment distance used) so callers can read it without having to look into stops[0] and test the flag. It contains the same data that is in stops[0].station but is NOT a contradictory representation — it is exactly the same station object, just repeated for consumer convenience. No contradiction possible because same underlying object.
  - **No retroactivity / no synthetic pricing.** In no case may a segment from route-mile S to E be priced using a station whose route mileage > S. A station located after a segment's start mile never prices fuel consumed during that segment.
  - DAG edge existence: milestone A → B exists iff B comes after A AND `distance(A,B) ≤ max_range_miles`.
  - Edge cost (A→B): `segment_gallons_consumed = distance(A,B) / mpg`; `segment_cost = segment_gallons_consumed * price_A` (where price_A = price of departure milestone A).
  - DP objective: min total_cost over all valid paths origin → destination.
  - Deterministic tie-break (equal total cost): (1) fewer non-origin stops, (2) stops at earlier route mileages preferred, (3) station nearer to the route polyline preferred, (4) higher sha256(natural_key) ascending preferred.
  - If destination unreachable under constraints → **HTTP 422** `code=NO_FEASIBLE_FUEL_PLAN`.
- **FR-8**: Response shape includes these exact top-level keys:
  ```
  route: { start{label,latitude,longitude}, finish{label,latitude,longitude}, distance_miles, duration_seconds, geometry{type=LineString,coordinates} }
  vehicle: { max_range_miles, miles_per_gallon, fuel_type }
  estimated_fuel_consumed_gallons   (Decimal, top-level)
  fuel_plan: {
     stops: FuelStop[]          // includes origin catchment as stops[0] with is_origin_catchment_entry=true
     total_stops: int           // non-origin count only; so direct route w/ 1 origin entry = total_stops 0
     total_gallons_consumed: Decimal    // sum over ALL stops incl stops[0]
     total_cost: Decimal               // sum over ALL stops incl stops[0]
     currency: "USD"
     cost_model: "segment_consumption_priced_at_departure_stop"
     algorithm: "ordered-dag-dynamic-program"
     origin_fueled_at_stop_index: null   // ALWAYS null, by rule
     origin_catchment_station: {opis_id, name, address, city, state, price_used, catchment_distance_miles} | null
     origin_catchment_radius_miles_used: float
  }
  assumptions: string[]
  data_quality: {
     fuel_station_records_loaded:  int
     stations_with_coordinates:   int (distinct natural_key_hash with lat/lng)
     stations_considered:         int (pre-dedupe corridor candidate count)
     candidate_station_count:     int (post-dedupe entering optimizer)
     external_provider_calls:     int (Nominatim + OSRM calls actually performed this request)
     cache_hits:                  int (cached responses reused this request)
  }
  ```
  (Names exact; NO field named `candidate_corridor_miles`.)
- **FR-9**: Each `fuel_plan.stops[i]` object contains these exact keys:
  - `is_origin_catchment_entry`: bool (true only when i=0)
  - `station`: object with opis_truckstop_id (string|null), name, address, city, state, rack_id (string|null)
  - `route_mileage_at_station` (Decimal)
  - `price_used_per_gallon` (Decimal — this station's price, used for the segment that DEPARTS FROM this station per cost_model rule)
  - `segment_start_route_mileage` (Decimal)
  - `segment_end_route_mileage` (Decimal)
  - `segment_distance_miles` (Decimal)
  - `segment_gallons_consumed` (Decimal)
  - `segment_cost` (Decimal)
  - `station_distance_from_route_miles` (float)
- **FR-10**: USA validation:
  - Text start/finish: Nominatim geocode + strict `country_code == 'us'` check (failure → HTTP 400 `code=LOCATION_OUTSIDE_USA`).
  - Coordinate start/finish: no reverse-geocode (extra provider call). Instead apply a documented heuristic USA bounding-box filter (contiguous USA + AK + HI ranges). Request assumptions list explicitly includes "Coordinate input USA validation is a bounding-box heuristic; no reverse geocode performed. Text inputs perform exact country check via Nominatim." Coordinates failing heuristic → HTTP 400 `code=LOCATION_OUTSIDE_USA_HEURISTIC`.
- **FR-11**: Providers: Nominatim via HTTP interface; OSRM via HTTP with `overview=full&geometries=geojson&steps=false`. Geometry LineString consumed VERBATIM from OSRM JSON response → stored in RouteCache.geometry_geojson → returned verbatim. NO polyline decode package. Deterministic sha256 cache keys based on normalized inputs + provider base URL. DB cached. Timeouts: Nominatim 5 s, OSRM 10 s. Failures mapped: ProviderTimeout → HTTP 504, ProviderError → HTTP 502, each with a specific `code` field (e.g., `NOMINATIM_TIMEOUT`, `OSRM_PROVIDER_ERROR`).
- **FR-12**: Candidate station corridor selection:
  - Query: `FuelPriceRecord.objects.filter(latitude__isnull=False, longitude__isnull=False)`.
  - For each station: compute point-to-polyline haversine-based approximate distance to every segment of route geometry; keep min distance (miles).
  - If distance ≤ `CORRIDOR_WIDTH_MILES` (default 25): project station onto nearest route segment → get its cumulative route mileage along the polyline.
  - Deduplicate by `natural_key_hash` → keep the record with the LOWEST `retail_price` per key (ties broken by earlier insert timestamp ascending).
  - Sort final list by projected cumulative route mileage ascending.
  - No per-station HTTP routing calls or geocoding ever performed here.
- **FR-13**: `GET /api/v1/health/` → HTTP 200 `{"status":"ok","service":"spotter-assessment","version":"1.0.0"}`. No external provider contact.
- **FR-14**: Validation: missing start/finish → HTTP 400; non-positive range/mpg → HTTP 400; latitude outside [-90,90] / longitude outside [-180,180] → HTTP 400; unknown JSON shape → HTTP 400 with DRF structured field errors.

### Testing rules
- **FR-15**: Automated tests MUST NOT contact public Nominatim or OSRM. All provider access via injectable ABC interfaces. Mock implementations return canned data and track call counts. Caching tests use real DB tables + wrapped mocks to exercise cache layer and ensure 0 HTTP on repeats.

## Non-Functional Requirements
- **NFR-1 (Exact Django LTS rule)**: Django LTS version. EXACT resolved version (not "latest", not "5.0.x", not `>=`) is: during Task 1, install Django from the current LTS release line using pip with a real venv; read the exact Version: X.Y.Z string reported by `pip show Django`; write THAT exact literal string into requirements.txt (e.g., `Django==5.2.1`) and README Installation section and Section 15. NO version range specifiers in requirements.txt for Django. NO attempt in spec to predict the string.
- **NFR-2**: DB indexes. FuelPriceRecord unique_together (natural_key_hash, source_row_id, source_file); index on (state, city); partial index on (latitude, longitude) WHERE non-null. GeocodeCache.cache_key UNIQUE. RouteCache.cache_key UNIQUE.
- **NFR-3**: Monetary arithmetic: Python `Decimal` for retail_price, price_used_per_gallon, segment_cost, segment_gallons_consumed, total_cost, both total gallons fields, distance_miles. Strict parsing per FR-1. NEVER `float` for money or volume.
- **NFR-4**: HTTP timeouts on every external call via httpx timeouts config. Bounded request body via DRF + Django DATA_UPLOAD_MAX_MEMORY_SIZE. CORS disabled (django-cors-headers not installed by default).
- **NFR-5**: ruff clean; compileall clean; manage.py check clean; migrate clean; git diff --check clean at final verification.
- **NFR-6**: OSRM request uses ONLY `geometries=geojson`. No `polyline` package appears in requirements.txt, setup files, or import statements anywhere. Route geometry stored/returned as OSRM-supplied GeoJSON dict.
- **NFR-7**: `data_quality` object uses EXACTLY the six integer field names from FR-8 response schema. No other names permitted.
- **NFR-8**: README contains every one of the assessment prompt's 16 sections. Section 10 (Fuel assumptions) mirrors FR-7 VERBATIM, including the origin stop inclusion flag rule, `total_stops` counting convention, origin_fueled_at_stop_index always null, origin_catchment_station convenience object rule. Section "How duplicate fuel records are handled" = FR-1 dedupe logic VERBATIM. Section on "External call count and caching strategy" matches FR-11 cache behavior and specifies max 3 first-run calls (2 geocode text + 1 OSRM) and 0 cached-hit runs.
- **NFR-9**: LOOM_SCRIPT.md explicitly includes (a) the `load_demo_fixture` step BEFORE runserver and narrates the approximate-coordinate honest labeling, (b) the exact `cost_model` string when explaining fuel plan, (c) NO mention of "full tank" / "initial fuel" anywhere, (d) exact mention that origin catchment 5 mi rule applies and a failing origin catchment yields 422 with the exact detail text, (e) shows a direct route response where stops.length=1 but total_stops=0 and explains the counting rule aloud.
- **NFR-10**: Dockerfile omits `.env.example → .env` copy; runtime env via compose or docker run -e. Deliverables present: README.md, LOOM_SCRIPT.md, IMPLEMENTATION_NOTES.md, .env.example, requirements.txt, Dockerfile, .github/workflows/ci.yml, src/manage.py, src/config/, src/routing/, src/routing/fixtures/demo_stations_with_approximate_coordinates.json (with `_provenance` labeling coordinates as approximate corridor demo placements).

## Constraints
- **Technical**: Django LTS + DRF; SQLite; Nominatim/OSRM default URLs; NO polyline decode; strict Decimal parse no scrub; corridor approx only (no PostGIS); deterministic algorithms only; no per-station HTTP in plan path; origin catchment required, no retroactive pricing; origin catchment station ALWAYS the first stops-list entry with `is_origin_catchment_entry=true`; origin_fueled_at_stop_index ALWAYS null.
- **Business**: Must not invent fuel prices; must not hard-code a route or fixed station list; must not silently hide assumptions (ALL enumerated in A-1..A-n below and in every response `assumptions` list); must not expose secrets.
- **Dependencies**: fuel-prices-for-be-assessment.csv present at repo root. Python 3.12+ available.

## Assumptions (copied VERBATIM into README Section 15 and every response `assumptions` list)
A-1: No physical tank simulation is attempted, because the request supplies neither tank capacity nor initial fuel level. The response therefore reports fuel in two independent places: (1) `estimated_fuel_consumed_gallons` top-level = total the route will burn regardless of stops, and (2) `fuel_plan.*` which estimates route cost under `cost_model = "segment_consumption_priced_at_departure_stop"` using `max_range_miles` solely as the maximum distance between consecutive milestones. Phrases "full tank", "tank capacity", and "initial fuel level" are not used and do not describe system behavior.

A-2: Origin catchment required. A fuel station must exist within `ORIGIN_CATCHMENT_RADIUS_MILES` (default 5 mi) of the route start point. If absent → HTTP 422 NO_FEASIBLE_FUEL_PLAN with exact detail text. If present → that station becomes milestone 0 price source and is INCLUDED as `fuel_plan.stops[0]` with `is_origin_catchment_entry=true`. Its entry contains the first segment from mile 0 to the next milestone. `fuel_plan.total_stops` = count of non-origin stops only, so a direct route ≤ range yields `stops.length=1, total_stops=0`. `fuel_plan.origin_fueled_at_stop_index` is always `null` because origin is pinned directly. `fuel_plan.origin_catchment_station` is provided as a convenience object with the same data.

A-3: No retroactive segment pricing. A segment S→E is always priced at a milestone station whose route position ≤ S.

A-4: Duplicate CSV record handling. Every valid source row is inserted (preserved individually) in FuelPriceRecord (unique_together natural_key_hash+source_row_id+source_file). Candidate selection groups by natural_key_hash and retains the single lowest-price record per key. Ties (same price same key) broken by earliest imported_at.

A-5: Station latitude/longitude strategy (two explicit paths, honestly labeled, NO fabrications labeled genuine geocodes):
  (a) PRIMARY for Loom demo and CI: `python manage.py load_demo_fixture` loads `demo_stations_with_approximate_coordinates.json` (~200 stations). Coordinates in this fixture are **APPROXIMATE CORRIDOR PLACEMENTS ALIGNED TO THE LISTED CITY/STATE OF EACH CSV STATION FOR THE CHICAGO→DENVER I-80 CORRIDOR DEMO**. They are NOT genuine Nominatim address-level geocodes; NOT city centroids (they are placed along the actual interstate corridor the CSV station would logically serve); sufficient for the assessment Loom demo, candidate corridor math, and fuel optimization. Fixture JSON `_provenance` documents this explicitly with full transparency.
  (b) OPTIONAL for operators who want real coordinates: `python manage.py geocode_stations --all --limit <N>` performs Nominatim-based address geocoding with 1 s pacing, DB caching, dry-run, limit, timeouts. Documented as slow + subject to Nominatim public usage policy.
  Route request path NEVER geocodes stations. If zero records with coords loaded → HTTP 428 per FR-4.

A-6: USA validation heterogeneity. Text-location inputs: Nominatim `country_code == 'us'` (exact). Raw coordinate inputs: heuristic bounding box USA filter only (no reverse geocode; documented explicitly).

A-7: Corridor width default = 25 miles (env configurable). Station-to-route distance approximated via equirectangular-projection + haversine point-to-segment distance, documented as demo-grade (production would use PostGIS ST_Distance with geography).

A-8: OSRM `geometries=geojson`. Response geometry is the OSRM LineString verbatim. No polyline decode package or logic.

A-9: Vehicle defaults when request omits them: max_range_miles = 500, miles_per_gallon = 10, fuel_type = "regular". All positive validated.

A-10: Caching behavior. Nominatim text query cache and OSRM coordinate-pair cache live in DB tables, deterministic sha256 keys over normalized inputs + provider base URL, TTL columns nullable default NULL (assessment default = permanent cache; production would add TTL enforcement + Redis). Repeat identical text→text plan request → 0 external calls, cache_hits ≥ 2, external_provider_calls = 0.

A-11 (Exact Django LTS pinning rule): During Task 1, pip install the currently supported Django LTS release into a real venv, read the EXACT patch version from `pip show Django`, and write that exact `Django==X.Y.Z` string into requirements.txt and README. No version ranges, no guesses, no "or latest" phrasing.

A-12: Strict price parsing. Retail Price column accepted only via `Decimal(value.strip())`. Any failure → row marked invalid with line number + reason, not inserted, reported in import summary. No regex scrubbing or coercion.

A-13: No synthetic origin price. No silent substitution of first downstream station to price origin-premium miles. Origin catchment failure is a hard 422; the caller must either use the demo fixture, run the Nominatim prep command, widen the `ORIGIN_CATCHMENT_RADIUS_MILES` env var, or choose a start location near available data.

## Acceptance Criteria

### AC-1: CSV import idempotent, strict decimal parse, whitespace normalized
- **Type**: `rule`
- **Given**: Fresh DB, mini 5-row fixture CSV with a bad Retail Price cell (value "N/A")
- **When**: `import_fuel_prices` run twice on fixture
- **Then**: Run 1 inserts 4 valid rows and reports exactly 1 invalid row with line number + reason string "Invalid Decimal for Retail Price: 'N/A'" (strict non-scrubbing message contains original raw value); Run 2 inserts 0 new rows (idempotent); stored name/city/state/address whitespace collapsed; loaded price type Decimal, exact repr matches input trimmed value; no float conversion artifacts.
- **Pass Condition**: test_import.py sub-tests all green.
- **Evidence**: pytest tests/test_import.py.

### AC-2: Station coordinate strategy. 428 before prep; load_demo_fixture succeeds & labels coordinates honestly; geocode_stations respects pacing/caching/dry-run/limit
- **Type**: `rule`
- **Given**: Fresh DB + CSV import complete but 0 coords.
- **When**:
  (a) POST any plan request → HTTP 428 code=STATION_COORDINATES_NOT_PREPARED, detail references BOTH `load_demo_fixture` AND `geocode_stations`.
  (b) Run `load_demo_fixture` → ≥150 FuelPriceRecord rows get non-null lat/lng.
  (c) Inspect fixture file → root key `_provenance` exists and contains text "approximate corridor" / "NOT genuine address geocodes" / "demo purposes only" honest labeling (NOT "real Nominatim results").
  (d) Then POST Chicago→Denver plan → 200; data_quality.stations_with_coordinates ≥ 150.
  (e) Separately run `geocode_stations --all --limit 3 --dry-run --pacing-seconds 0.5` with MockGeocoder → 0 DB writes, exactly 3 attempted resolve prints, inter-call pacing delay honored (≥ 0.5 s observed or mocked sleep count).
- **Then**: Sub-cases (a)(b)(c)(d)(e) all pass.
- **Pass Condition**: All five sub-conditions verified.
- **Evidence**: pytest test_geocode_command.py + test_api.py 428 case + fixture file content assertion.

### AC-3: Response shape & arithmetic including origin entry inclusion flag rule & total_stops counting rule
- **Type**: `rule`
- **Given**: Mocked providers Chicago→Denver ~1000 mi route, demo fixture loaded (includes station ≤ 5 mi of Chicago), vehicle defaults mpg=10 range=500.
- **When**: POST text start/finish.
- **Then**:
  1. HTTP 200.
  2. `estimated_fuel_consumed_gallons == Decimal("100.0")` (top-level, independent of stops).
  3. `fuel_plan.cost_model == "segment_consumption_priced_at_departure_stop"` exact.
  4. `fuel_plan.stops.length ≥ 1`; `stops[0].is_origin_catchment_entry is true`; remaining stops entries have `is_origin_catchment_entry is false`.
  5. `stops[0].segment_start_route_mileage == 0` exact (origin entry covers mile-0 first segment per rule).
  6. Σ stops[*].segment_cost == fuel_plan.total_cost Decimal exact equality.
  7. Σ stops[*].segment_gallons_consumed == fuel_plan.total_gallons_consumed Decimal exact equality, AND both sums include stops[0] contribution.
  8. `fuel_plan.total_stops == count of stops with is_origin_catchment_entry==false` (definition). In a synthetic 1000-mi / range-500 scenario with stops at origin + mile 400 + mile 900 → stops.length=3 → total_stops=2 (non-origin). Verify via test.
  9. `fuel_plan.origin_fueled_at_stop_index is null` ALWAYS.
  10. `fuel_plan.origin_catchment_station` object present, == equal to stops[0].station fields plus catchment distance info (no contradictory data).
  11. geometry.type == "LineString".
  12. data_quality object keys EXACTLY: fuel_station_records_loaded, stations_with_coordinates, stations_considered, candidate_station_count, external_provider_calls, cache_hits. No extra; none missing; none renamed.
- **Pass Condition**: 12 sub-conditions all true in API test.
- **Evidence**: test_api.py `test_response_shape_arithmetic_and_origin_stop_inclusion`.

### AC-4: Optimizer correctness. Eight cases under origin-inclusion model
- **Type**: `rule`
- **Given**: Deterministic tiny synthetic fixtures.
- **When**: Run optimizer on each:
  (a) 300 mi route ≤ range 500, origin catchment hit price $3.00, mpg=10. No intermediate candidates. Result: stops.length=1 (origin only); total_stops=0; total_gallons_consumed=30; total_cost=90.00 Decimal; stops[0].is_origin_catchment_entry=true; stops[0].segment_start=0, segment_end=300; origin_fueled_at_stop_index=null.
  (b) 1000 mi, range 500, origin $3.00, candidate at 400 $3.00, candidate at 900 $3.50. Valid edges origin→400 (400), 400→900 (500 exact boundary = allowed), 900→1000 (100). Stops list length=3 (origin + 400 + 900). Total_stops=2 (non-origin). Segment costs: 400/10×3=120; 500/10×3=150; 100/10×3.5=35. Total_cost=305, total_gallons_consumed=100.
  (c) 1500 mi range 500; origin $3.2 at mile 0; candidates at mile 300@$3.0, 600@$2.8 (cheapest), 900@$2.9, 1200@$3.1. DP uses cheapest reachable departure prices; totals correct & path is min-cost.
  (d) Dataset has a $2.00 station at mile 100, but it is deliberately EXCLUDED from the candidate list passed to optimizer (simulating corridor filter rejection). Optimal result must be numerically identical to a separate run in which that station never existed; optimizer does not "see" filtered stations.
  (e) Two candidates at the same mile, equal prices, different natural keys; optimizer run 10× → identical ordered stops lists every time (deterministic tie-break stable across runs).
  (f) 2000 mi, range 400, stations ONLY at origin and destination; no intermediates → NoFeasiblePlanError → HTTP 422.
  (g) Two nodes 500.0 mi apart exactly, max_range_miles = 500 → edge exists and is used by optimal path.
  (h) Arithmetic invariant on ANY success: each stop individually: stop.segment_cost == stop.segment_gallons_consumed * stop.price_used_per_gallon Decimal exact; total sums across ALL stops (including origin stop[0]) equal fuel_plan totals; no stop is ever priced at a station whose position is > segment start mile.
- **Pass Condition**: 8 optimizer sub-cases all pass in test_optimizer.py.
- **Evidence**: pytest -v tests/test_optimizer.py. No test names or docstrings contain the forbidden tank phrases.

### AC-5: Coordinate input + USA heuristic behavior
- **Type**: `rule`
- **Given**: Plan request with raw coords Chicago (41.88,-87.63) → Denver (39.74,-104.99). Separate request with Paris coords (48.8566, 2.3522).
- **When**: Both requests POSTed with demo fixture preloaded.
- **Then**: Chicago→Denver: Nominatim text-geocode provider call count = 0 (no text to resolve); route still computed; response `assumptions` list contains exact A-6 sentence "Coordinate input USA validation is a bounding-box heuristic; no reverse geocode performed. Text inputs perform exact country check via Nominatim." Paris coords: HTTP 400 with `code=LOCATION_OUTSIDE_USA_HEURISTIC`.
- **Pass Condition**: Both sub-cases pass; 0 geocode calls on coord path; assumption text present.
- **Evidence**: test_api.py `test_coord_input_skips_geocode_and_uses_usa_heuristic`.

### AC-6: Provider failure safe handling
- **Type**: `rule`
- **Given**: Mocked providers set to raise (a) Nominatim ProviderTimeoutError on Chicago text query; (b) OSRM ProviderError on route.
- **When**: Plan request POSTed in each scenario.
- **Then**: (a) → HTTP 504 body `{"code":"NOMINATIM_TIMEOUT", ...}`; (b) → HTTP 502 body `{"code":"OSRM_PROVIDER_ERROR", ...}`; neither response contains stack trace or Python exception string (DEBUG=False enforced).
- **Pass Condition**: Status codes exact, code fields exact, no traceback leaked.
- **Evidence**: test_api.py failure-mode tests.

### AC-7: Caching eliminates duplicate external calls
- **Type**: `rule`
- **Given**: Two IDENTICAL Chicago→Denver text plan requests back-to-back; mock provider call counters.
- **When**: Req1 then Req2.
- **Then**: Req1: external_provider_calls ≤ 3 (2 text + 1 route). Req2: external_provider_calls = 0 EXACTLY, cache_hits ≥ 2 (at minimum start+finish geocode, likely 3), route response identical to Req1 except data_quality counters.
- **Pass Condition**: Req2 provider 0 HTTP calls verified via mock call counters.
- **Evidence**: test_api.py cache test.

### AC-8: Full automated test suite passes (pytest -q) offline
- **Type**: `rule`
- **Given**: No network access to Nominatim/OSRM.
- **When**: `cd src ; pytest -q` executed.
- **Then**: Exit 0, > 0 tests ran, all PASSED. No live outbound sockets (mocks only).
- **Pass Condition**: Exit code 0, output captured.
- **Evidence**: Task 11 captured pytest run.

### AC-9: Lint/check/build commands clean
- **Type**: `rule`
- **Given**: Final code.
- **When**: Execute in order: python --version; python -m compileall src; cd src && python manage.py check; cd src && python manage.py migrate; cd src && python manage.py import_fuel_prices ../fuel-prices-for-be-assessment.csv; cd src && python manage.py load_demo_fixture; cd src && pytest -q; ruff check .; git diff --check; git status --short.
- **Then**: Zero non-zero exit codes from the 9 tool commands (git status can report uncommitted files naturally; git diff --check must exit 0 = no whitespace errors).
- **Pass Condition**: 9 commands × 0 exit codes.
- **Evidence**: Task 11 captured stdout/stderr.

### AC-10: README completeness & correctness
- **Type**: `rubric`
- **Dimension**: README 16 sections, content matches spec behavior exactly.
- **Scale**: 1-5
- **Anchors**:
  1 = Missing 6+ sections OR contains ANY of the forbidden tank phrases OR uses wrong cost_model string OR fails to document the demo fixture's approximate-coordinate honest labeling.
  3 = Most sections present but origin stop inclusion rule, total_stops counting definition, or origin_fueled_at_stop_index=null rule not documented.
  5 = All 16 sections present; Section 10 contains exact cost_model string; Section 10 explicitly documents stops[0] is origin with flag true, total_stops excludes origin stops, origin_fueled_at_stop_index always null, origin_catchment_station convenience copy; A-5 fixture provenance labeled as approximate-corridor NOT genuine geocodes; Section 9 says max 3 calls first-run, 0 on repeat; Section 15 copies all 13 A-* bullets; Mermaid diagram present.
- **Pass Threshold**: >= 4.
- **Evidence**: README text grep + section count.

### AC-11: Architecture layering quality
- **Type**: `rubric`
- **Dimension**: Provider DI + separation.
- **Scale**: 1-5
- **Anchors**: 1 = Logic in views, no interfaces. 3 = Services exist but tests monkeypatch internal URLs. 5 = ABC GeocodeProvider/RoutingProvider; Nominatim/OSRM thin HTTP impls; Cached* via composition; corridor and optimizer pure modules; route_planner thin orchestration; views only serialize and map exceptions to HTTP codes; tests/mocks.py instantiates ABC subclasses and injects.
- **Pass Threshold**: >= 4.
- **Evidence**: Code review.

### AC-12: Loom script completeness & consistency
- **Type**: `rubric`
- **Dimension**: 5-min demo exactness.
- **Scale**: 1-5
- **Anchors**:
  1 = Skips load_demo_fixture step OR uses forbidden "full tank" phrase OR explains total_stops incorrectly OR says demo coords are real Nominatim geocodes.
  3 = Most steps present but skips the direct-route stops=1/total_stops=0 explanation or the 422 origin-catchment demo.
  5 = All 10 prompt demo items covered; exact commands include `load_demo_fixture` BEFORE runserver with honest narration "approximate corridor coordinates for demo use only — real operators should run geocode_stations"; Step 4/5 response walk explicitly points to stops[0] and reads: "first entry origin catchment is_origin_catchment_entry true; total_stops count excludes origin stops so here total_stops=X even though stops has X+1 entries including origin"; cost_model exact string spoken; Step 8 demo returns 422 start location far from any corridor station (e.g., Honolulu if not in demo data) showing exact origin-catchment detail text; Step 10 assumption recap explicitly says "no tank model — max_range only limits inter-milestone distance"; total timing ≤5:15; zero forbidden tank phrase occurrences.
- **Pass Threshold**: >= 4.
- **Evidence**: LOOM_SCRIPT.md.

### AC-13: All deliverables present
- **Type**: `rule`
- **Given**: Final repo tree.
- **When**: Existence check for README.md, LOOM_SCRIPT.md, IMPLEMENTATION_NOTES.md, .env.example, requirements.txt, Dockerfile, .github/workflows/ci.yml, src/manage.py, src/config/, src/routing/, src/routing/fixtures/demo_stations_with_approximate_coordinates.json (inside JSON top-level `_provenance` key present).
- **Then**: Every path exists. docker-compose.yml is optional extra.
- **Pass Condition**: 11 required filesystem objects all present.
- **Evidence**: Task 11 captured tree.

## Open Questions
None. All three final consistency fixes applied uniformly across spec.
