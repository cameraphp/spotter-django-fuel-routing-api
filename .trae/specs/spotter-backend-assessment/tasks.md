# Spotter Backend Django Engineer Assessment - Implementation Plan

## Task 1: Resolve Django LTS version EXACTLY + project scaffolding + deps + env.example
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  1. **Exact Django LTS pin (NO ranges / guesses)**: Create fresh Python 3.12 venv in a `_tmp_resolve_venv` subdirectory. Run:
     `pip install Django djangorestframework httpx pytest pytest-django ruff python-dotenv`.
     Then run `pip show django | grep Version` to capture EXACT Version X.Y.Z string. Also run `python -m django --version` cross-check. Record that string literal for later.
     If Django 5.2 LTS line is available, it will be picked up as latest LTS; otherwise Django 4.2.x LTS (the prior supported line) will be installed and pinned. No hand-picked version strings in spec — pip resolves it.
  2. **Create src/ tree**: `manage.py`, `config/__init__.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `config/asgi.py`.
  3. **Create routing/ app skeleton**:
     `__init__.py`, `apps.py`, `admin.py`, `models.py`, `serializers.py`, `views.py`, `urls.py`.
     Subpackages/dirs: `services/` (__init, geocoding, routing_provider, fuel_candidates, fuel_optimizer, route_planner, errors).
     `management/commands/` (__init, import_fuel_prices, load_demo_fixture, geocode_stations).
     `tests/` (__init, conftest, mocks, test_import, test_geocode_command, test_candidates, test_optimizer, test_route_planner, test_api).
     `fixtures/` (empty dir, demo JSON added in Task 7).
  4. **Write requirements.txt** with EXACT pinned versions: Django==<VERSION-FROM-STEP-1>, djangorestframework==3.15.2, httpx==0.27.2, pytest==8.3.3, pytest-django==4.9.0, ruff==0.6.9, python-dotenv==1.0.1.
     - IMPORTANT grep check: NO line containing `polyline`; NO Django line with `>=` `<` `~=` `or` "latest" "LTS" — just exact `Django==X.Y.Z`.
  5. **`.env.example`** with env vars: NOMINATIM_URL, NOMINATIM_USER_AGENT, NOMINATIM_PACING_SECONDS (1.0), OSRM_URL, HTTP_TIMEOUT_SECONDS (15), CORRIDOR_WIDTH_MILES (25), ORIGIN_CATCHMENT_RADIUS_MILES (5), DEFAULT_MAX_RANGE_MILES (500), DEFAULT_MPG (10), DEFAULT_FUEL_TYPE (regular).
  6. **`config/settings.py`**: INSTALLED_APPS=['routing', 'rest_framework']; DATABASES sqlite; dotenv `load_dotenv()`; SECRET_KEY from env; DEBUG=False (never True default); DATA_UPLOAD_MAX_MEMORY_SIZE=524288; DRF JSON-only renderers/parsers; ALLOWED_HOSTS=['*'] for assessment only.
- **Acceptance Criteria Addressed**: NFR-1, NFR-4, NFR-6, NFR-10, A-11, AC-9, AC-13
- **Test Requirements**:
  - `rule` TR-1.1: `cd src ; python manage.py check` exits 0.
  - `rule` TR-1.2: `python -m compileall src` exits 0.
  - `rule` TR-1.3: requirements.txt Django line matches exact `==X.Y.Z` format AND `rg 'polyline' requirements.txt` returns no matches.
  - `rule` TR-1.4: `.env.example` has ORIGIN_CATCHMENT_RADIUS_MILES and NOMINATIM_PACING_SECONDS lines.
- **Notes**: Preserve the captured Django exact version in this task's completion evidence for later docs.

## Task 2: Database models + errors + 0001_initial migration
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `routing/models.py`:
    - `FuelPriceRecord`: id PK; source_opis_id; station_name; address; city (indexed); state 2-char indexed; rack_id; retail_price Decimal(12,9); normalized_search_text indexed; natural_key_hash char(64) indexed; source_row_id int; source_file; imported_at auto_now_add; latitude Decimal(10,7) null indexed; longitude Decimal(10,7) null indexed; geocoded_at DateTime null.
      Meta unique_together = [("natural_key_hash", "source_row_id", "source_file")].
      Meta indexes = [("state", "city"), ... partial index on (latitude, longitude)].
    - `GeocodeCache`: cache_key char(64) UNIQUE; query_text; latitude Decimal; longitude Decimal; display_label; country_code char(5) null; raw_json JSONField; created_at auto_now_add; ttl_expires_at DateTime null.
    - `RouteCache`: cache_key char(64) UNIQUE; start_lat start_lng finish_lat finish_lng Decimal; distance_miles Decimal; duration_seconds int; geometry_geojson JSONField; raw_provider_json JSONField; created_at auto_now_add; ttl_expires_at DateTime null.
  - `services/errors.py`: ProviderTimeoutError, ProviderError, NoFeasiblePlanError (default code=NO_FEASIBLE_FUEL_PLAN), StationCoordinatesNotPrepared (code=STATION_COORDINATES_NOT_PREPARED), USAValidationError (sub_code "NOMINATIM" or "HEURISTIC").
  - Run `cd src ; python manage.py makemigrations routing` to create 0001_initial.py. Verify migration file references all fields.
- **Acceptance Criteria Addressed**: FR-1, FR-2, FR-3, FR-4, NFR-2, NFR-3, AC-1, AC-2
- **Test Requirements**:
  - `rule` TR-2.1: `cd src ; python manage.py migrate` exits 0.
  - `rule` TR-2.2: Insert retail_price=Decimal("2.68733333") → read back → type Decimal exact repr equality, no float conversion.
  - `rule` TR-2.3: Insert same (natural_key_hash, source_row_id, source_file) twice → 2nd insert integrity error or skipped per idempotent get_or_create.

## Task 3: Provider ABCs + Nominatim/OSRM (geometries=geojson ONLY) + Cached wrappers + USA heuristic fn
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `services/geocoding.py`:
    - GeocodeResult NamedTuple (lat Decimal, lng Decimal, label str, country_code Optional[str]).
    - GeocodeProvider ABC with resolve(query str) -> GeocodeResult.
    - NominatimGeocoder(GeocodeProvider): httpx GET `{base_url}/search` with params (q, format=jsonv2, limit=1, addressdetails=1); User-Agent header from settings; timeout; map nominatim country_code to lower; raise ProviderError/ProviderTimeoutError appropriately.
    - CachedGeocoder(GeocodeProvider): wraps inner; cache_key = sha256_hex(class_name + base_url + normalized_query_lower); SELECT GeocodeCache → if hit & ttl valid return; else call inner; INSERT cache. Track cache_hit boolean attribute for counters.
    - is_usa_heuristic(lat,lng) bool → contiguous USA box + AK + HI ranges. Documented as demo-grade, not reverse geocoded.
  - `services/routing_provider.py`:
    - RouteResult NamedTuple (distance_miles Decimal, duration_seconds int, geometry_geojson dict, raw dict).
    - RoutingProvider ABC with route(start_lat, start_lng, finish_lat, finish_lng) -> RouteResult.
    - OSRMRoutingProvider(RoutingProvider): httpx GET `{base_url}/route/v1/driving/{start_lng},{start_lat};{finish_lng},{finish_lat}`. Query params: overview=full, geometries=geojson, steps=false. NO polyline. Parse meters→miles Decimal; duration seconds int; routes[0].geometry stored VERBATIM (already LineString dict w/ coordinates). Raise errors correctly.
    - CachedRoutingProvider(RoutingProvider): cache_key sha256 class + base_url + 6dp coords; hit RouteCache or call & INSERT. Track cache_hit.
- **Acceptance Criteria Addressed**: FR-10, FR-11, A-6, A-8, A-10, NFR-6, AC-5, AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-3.1: MockGeocoder(GeocodeProvider) subclass returns canned data; no httpx in test.
  - `rule` TR-3.2: CachedGeocoder same query twice → inner provider.resolve call_count EXACTLY = 1. 2nd hit GeocodeCache DB.
  - `rule` TR-3.3: Intercept OSRMRoutingProvider httpx GET URL → substring `geometries=geojson` present, `geometries=polyline` ABSENT (fail if present).
  - `rule` TR-3.4: geometry_geojson from impl has `type=="LineString"` and `coordinates` list; no decoding step.
  - `rule` TR-3.5: is_usa_heuristic on Chicago True, on Paris False.

## Task 4: Haversine + point-to-segment + corridor projection + dedupe by natural key lowest price + origin catchment find
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - `services/fuel_candidates.py`:
    - haversine_miles(lat1, lng1, lat2, lng2) -> float (R 3958.8 mi).
    - point_to_segment_miles(p, a, b) -> (distance_miles, proj_lat, proj_lng, t_frac_0_to_1) equirectangular demo-grade approx docstring.
    - build_cumulative_distances(route_coords:[[lng,lat]]) -> list[float] cumulative vertex haversine sums.
    - project_station_onto_route(station_lat, station_lng, route_coords, cumulative_distances, corridor_width_miles) -> Optional (distance_from_route_miles, route_mileage, proj_lat, proj_lng). None if min distance > corridor_width.
    - select_candidates(route_coords, cumulative_distances, stations_qs, corridor_width_miles) -> list[Candidate] where Candidate NamedTuple = (fuel_price_record, distance_from_route_miles, route_mileage, haversine_from_origin_miles). Deduplicate by natural_key_hash KEEP ONLY the record of MINIMUM retail_price per key (ties by earliest id). Return sorted by route_mileage ascending. Return also pre_dedupe_count integer for data_quality.stations_considered.
    - find_origin_catchment_station(candidates, origin_lat, origin_lng, origin_catchment_radius_miles) -> Optional Candidate: filter candidates by haversine(origin, station) + station.distance_from_route_miles ≤ radius; return candidate with minimum combined distance, tie-break lower price. None → caller raises 422 origin catchment.
- **Acceptance Criteria Addressed**: FR-7, FR-12, A-7, AC-2, AC-3, AC-4
- **Test Requirements**:
  - `rule` TR-4.1: haversine_miles(NYC≈40.71,-74.01, LA≈34.05,-118.24) ∈ [2440, 2460] miles.
  - `rule` TR-4.2: Station on midpoint route segment → distance < 0.05 mi; route_mileage ≈ total / 2.
  - `rule` TR-4.3: Station 100 mi distant corridor_width=25 → projection returns None.
  - `rule` TR-4.4: Two candidates same natural_key, prices $3.10 vs $2.90 → dedupe keeps $2.90 record.
  - `rule` TR-4.5: find_origin_catchment_station with catchment=5 mi, candidate at 10 mi → returns None.

## Task 5: Optimizer DP — milestone nodes, origin catchment station included as stops[0], total_stops excludes origin, no retroactivity, no tank language
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - `services/fuel_optimizer.py`:
    - Inputs: origin_lat/lng, destination_route_mileage_total, candidates list[Candidate], origin_catchment_station Optional[Candidate], max_range_miles, mpg.
    - Step 1 — origin catchment validation: if origin_catchment_station is None → raise NoFeasiblePlanError with the EXACT HTTP 422 detail text string spec FR-7. No delegation fallback.
    - Step 2 — build ordered nodes list:
      node[0] = (kind='origin', station=origin_catchment_station.fuel_price_record, price=Decimal(retail_price), route_mileage=Decimal(0), is_origin_catchment_entry=True, distance_from_route=..., natural_key=hash, is_destination=False).
      nodes [1..N-2] = each candidate in selected candidates list, SKIP candidate whose natural_key == origin_catchment_station natural_key (avoid duplicate origin double listing), node kind='stop', is_origin_catchment_entry=False, price=retail_price, route_mileage = candidate.route_mileage (Decimal).
      node[N-1] = (kind='destination', station=None, price=None, route_mileage=Decimal(round(total_miles, 6)), is_origin_catchment_entry=False, distance_from_route=0, natural_key='__DEST__', is_destination=True).
    - Step 3 — DP: dp[N] each entry = (min_total_cost Decimal, predecessor_idx int or None). dp[0] = (0, None). dp[1..] = (INF, None).
      Nested loops: for i 1..N-1: for j 0..i-1:
      seg_miles = nodes[i].route_mileage - nodes[j].route_mileage
      if seg_miles > max_range → skip.
      if seg_miles < 0 → skip.
      if nodes[j].is_destination or nodes[i].route_mileage == 0 and i != 0 → skip (never depart dest, never arrive at origin).
      price_p = nodes[j].price. Because nodes[0] always has a price (origin catchment ensured), every non-destination departure node has a price. No retroactivity, ever.
      seg_gallons = Decimal(str(seg_miles)) / Decimal(str(mpg))
      seg_cost = seg_gallons * price_p
      candidate_total_cost = dp[j][0] + seg_cost
      Tie-break: equal cost → (fewer stops path, then earlier route positions overall via predecessor chain depth, then nearer route, then natural key ascending).
      Apply update if wins tie.
    - If dp[N-1][0] is INF → raise NoFeasiblePlanError "Destination unreachable within max range" → 422.
    - Reconstruct predecessor chain from destination → collect segment events: list of (departure_node_idx, arrival_node_idx).
    - Build stops output list: one entry per departure node in the chain (origin departure node j=0 is ALWAYS included → per rule stops[0] = origin catchment entry). For each departure node j:
        - departure_node = nodes[j]
        - arrival_node = nodes[next_after_j_in_chain]
        - stop_entry dict:
          is_origin_catchment_entry = departure_node.is_origin_catchment_entry (True iff j == 0 → exactly one entry True)
          station = {opis_truckstop_id, station_name, address, city, state, rack_id}
          route_mileage_at_station = departure_node.route_mileage
          price_used_per_gallon = departure_node.price (price AT departure — by def segment is priced here)
          segment_start_route_mileage = departure_node.route_mileage
          segment_end_route_mileage = arrival_node.route_mileage
          segment_distance_miles = (end - start)
          segment_gallons_consumed = distance / Decimal(str(mpg))
          segment_cost = gallons * price_used_per_gallon
          station_distance_from_route_miles = departure_node.distance_from_route
    - Compute totals:
      total_stops = count entries with is_origin_catchment_entry == False (non-origin stops count only).
      total_gallons_consumed = sum(ALL stops[*].segment_gallons_consumed) INCLUDING stops[0] origin entry.
      total_cost = sum(ALL stops[*].segment_cost) INCLUDING stops[0].
      Validate totals equal DP final cost and DP gallons reconstructible.
    - Return FuelOptimizerPlan NamedTuple:
      stops (list dicts as above), total_stops int, total_gallons_consumed Decimal, total_cost Decimal, cost_model=LITERAL "segment_consumption_priced_at_departure_stop", algorithm="ordered-dag-dynamic-program", origin_fueled_at_stop_index=None (ALWAYS None by rule, not a convenience lookup index — we use stops[0] flag instead), origin_catchment_station dict (={same station as stops[0].station plus catchment_distance_miles_used float, price_used Decimal}), origin_catchment_radius_miles_used=float(env value).
  - Code + comments scan: NEVER write strings/comments/test names that include phrases "full tank", "tank capacity", "starts full", "initial fuel level", "fuel on board". If any occurrence → rewrite.
- **Acceptance Criteria Addressed**: FR-6, FR-7, FR-12, A-1, A-2, A-3, AC-4
- **Test Requirements**:
  - `rule` TR-5.1 Case (a): 300 mi ≤ range500, origin catchment $3.00, mpg10 → stops.length=1, stops[0].is_origin_catchment_entry=true, total_stops=0, total_gallons=30, total_cost=Decimal("90.00"), origin_fueled_at_stop_index IS None, stops[0].segment_start=0, segment_end=300.
  - `rule` TR-5.2 Case (b): 1000 mi range500 origin $3.00 mile0, mile400 $3.00, mile900 $3.50 → stops=[origin, mile400, mile900] (length 3). total_stops=2 (non-origin = mile400 + mile900). Segment costs: 400/10×3=$120 (origin dep), 500/10×3=$150 (mile400 dep), 100/10×3.5=$35 (mile900 dep). Total cost $305, total gallons 100.
  - `rule` TR-5.3 Case (c): 1500 mi 5 evenly spaced cheapest mile600 $2.8 exploited; DP totals correct.
  - `rule` TR-5.4 Case (d): globally cheapest station explicitly REMOVED before optimizer input → optimizer result numerically equal to a second run where it never existed.
  - `rule` TR-5.5 Case (e): two same mile same price candidates; run optimizer 10× → stops[*].station lists equal every run (deterministic tie).
  - `rule` TR-5.6 Case (f): 2000 mi range400 stations only at origin dest → NoFeasiblePlanError.
  - `rule` TR-5.7 Case (g): nodes distance exactly max_range → edge used.
  - `rule` TR-5.8 Case (h): any plan → Σ stops.segment_cost == total_cost exact Decimal; Σ stops.segment_gallons == total_gallons; each stop individually: stop.segment_cost == stop.segment_gallons_consumed * stop.price_used_per_gallon exact; origin_fueled_at_stop_index is None; stops[0].is_origin_catchment_entry true; stops[1:].is_origin_catchment_entry all false; Σ (1 for s in stops if NOT s.is_origin_catchment_entry) == total_stops.
  - `rule` TR-5.9 Origin catchment station None passed → raises NoFeasiblePlanError with EXACT detail text for HTTP 422 body (copy pasted from spec).

## Task 6: Route planner orchestrator + serializers + views + URLconf; exact HTTP codes; response schema matches spec 100%
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 3, Task 4, Task 5
- **Description**:
  - `services/route_planner.py plan_route(payload, geocoder, router) -> dict`:
    - Parse PlanRequestSerializer. Invalid → ValidationError → 400.
    - Resolve start/finish: if text → geocoder.resolve; USA check country_code us. If coords → use directly, USA=is_usa_heuristic + document A-6 in assumptions list. Failures raise USAValidationError (subcode).
    - Track external_provider_calls counter + cache_hits counter via wrapper providers with call-count attrs or via custom counter hooks; CachedGeocoder and CachedRouter expose call counts.
    - Call router.route → RouteResult. Extract route_coords.
    - Load stations_qs = FuelPriceRecord.objects.filter(latitude__isnull=False, longitude__isnull=False). If count 0 → raise StationCoordinatesNotPrepared with FR-4 detail text.
    - Build cumulative_distances.
    - select_candidates → candidates list + stations_considered pre-dedupe int.
    - find_origin_catchment_station → origin_cand or None. None → raise NoFeasiblePlanError origin catchment text.
    - Call optimizer with origin_cand → FuelOptimizerPlan.
    - Compute top_level estimated_fuel_consumed_gallons = distance_miles Decimal / Decimal(str(mpg)).
    - Build data_quality dict with EXACT 6 keys:
      fuel_station_records_loaded = FuelPriceRecord.objects.count()
      stations_with_coordinates = distinct natural_key with lat/lng count
      stations_considered = pre_dedupe int
      candidate_station_count = len(candidates)
      external_provider_calls = int
      cache_hits = int
    - assumptions = A-1 through A-13 13-item verbatim string list.
    - Return dict = route object, vehicle echo, top level estimated_fuel_consumed_gallons, fuel_plan FuelOptimizerPlan dict form, assumptions list, data_quality dict.
  - `serializers.py`:
    - CoordinateSerializer, VehicleSerializer, PlanRequestSerializer (start/finish accept str OR coord via custom to_internal_value), FuelStopSerializer exact 10 fields from FR-9, RouteSerializer, FuelPlanSerializer (includes stops list, total_stops int, total_gallons_consumed Decimal, total_cost Decimal, currency "USD" const, cost_model const, algorithm const, origin_fueled_at_stop_index IntegerField allow_null True, origin_catchment_station DictField or serializer, origin_catchment_radius_miles_used FloatField).
    - DataQualitySerializer 6 exact integer fields.
    - PlanResponseSerializer: route, vehicle, estimated_fuel_consumed_gallons DecimalField, fuel_plan, assumptions ListField(child=CharField), data_quality.
  - `views.py`:
    - HealthView GET → status ok exact json keys.
    - RoutePlanView POST: inject providers = CachedGeocoder(NominatimGeocoder(...)) + CachedRoutingProvider(OSRMRoutingProvider(...)); call plan_route; catch exceptions → exact codes/messages:
      Validation/USA → 400 with code fields.
      NoFeasiblePlanError → 422 NO_FEASIBLE_FUEL_PLAN.
      StationCoordinatesNotPrepared → 428 STATION_COORDINATES_NOT_PREPARED.
      ProviderTimeoutError → 504 <SUBSYS>_TIMEOUT.
      ProviderError → 502 <SUBSYS>_PROVIDER_ERROR.
      Unhandled → DEBUG False → generic 500 only.
  - config/urls include routing.urls prefix api/v1/.
  - routing/urls: POST routes/plan, GET health.
- **Acceptance Criteria Addressed**: FR-5 to FR-14 all, NFR-7, AC-3, AC-5, AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-6.1 HTTP 200. stops[0].is_origin_catchment_entry true. total_stops = stops count minus origin stops. origin_fueled_at_stop_index JSON null (None). data_quality 6 exact key names (not candidate_corridor_miles). fuel_plan.cost_model exact string.
  - `rule` TR-6.2 Missing finish → 400 structured field error.
  - `rule` TR-6.3 Infeasible → 422 code NO_FEASIBLE_FUEL_PLAN.
  - `rule` TR-6.4 0 station coords → 428 code STATION_COORDINATES_NOT_PREPARED + detail names load_demo_fixture AND geocode_stations.
  - `rule` TR-6.5 Health GET → 200 exact keys.
  - `rule` TR-6.6 2 identical text requests: second: data_quality.cache_hits ≥ 2, data_quality.external_provider_calls exactly 0.

## Task 7: Management commands (import_fuel_prices STRICT parse + load_demo_fixture approx coords honestly labeled + geocode_stations optional bulk)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2, Task 3, Task 1 (fixtures dir)
- **Description**:
  - `management/commands/import_fuel_prices.py`:
    Require headers: OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price (case/whitespace tolerant check). Missing → exit code 2 stderr.
    Iterate csv.DictReader: collapse and strip whitespace on station_name/address/city/state/rack_id using re.sub(r'\s+',' ',s).strip().
    **STRICT price parse ONLY**: try: retail_price = Decimal(row['Retail Price'].strip()) except (InvalidOperation, ValueError, TypeError) → invalid_rows append (line_number, "Invalid Decimal for Retail Price: {}".format(repr(row['Retail Price']))). SKIP INSERT; DO NOT scrub chars; DO NOT try to rescue.
    Required non-empty text fields check; else invalid.
    natural_key_hash = sha256(| joined normalized uppercased name|address|city|state).hexdigest().
    source_row_id = reader.line_num; source_file basename csv_path.
    Idempotent get_or_create by unique_together; try except IntegrityError or (get then create if not exists).
    Summary stdout: valid, invalid_count (verbose=2 prints each invalid row with line number and reason), duplicates_seen, new_created.
  - `management/commands/load_demo_fixture.py`:
    Load `routing/fixtures/demo_stations_with_approximate_coordinates.json`.
    JSON shape: top-level keys `_provenance` and `stations`.
    _provenance dict MUST contain these keys with these exact honest non-"genuine" labels:
      generated_at: ISO date time.
      coordinate_type: "approximate_corridor_placements_for_demo_only"
      description: "Approximate latitude/longitude values placed along the Chicago-to-Denver I-80 interstate corridor, keyed to the approximate listed city/state of each CSV truckstop record. NOT genuine Nominatim address-level geocode results. NOT city centroids. For Spotter assessment Loom demo and CI speed use only. For production-like coordinates run geocode_stations."
      source_dataset: "fuel-prices-for-be-assessment.csv"
      intended_use: "Demo fixture for assessment; 200 records selected to enable Chicago→Denver corridor math & fuel optimization."
    stations list entries: natural_key_hash, source_opis_id, source_city, source_state, station_name, latitude (approximate corridor float), longitude (approximate corridor float), source_csv_identification (e.g., "Matches OPIS Truckstop ID {id} + City/State in CSV").
    Command: match rows by opis_id + city/state or natural_key, UPDATE matching FuelPriceRecord rows latitude/longitude/geocoded_at now; print count updated.
    Actually create the fixture JSON file on disk in routing/fixtures: populate ~200 records with realistically spaced I-80 corridor approximate coords (e.g., progress from Chicago west to Denver at roughly 5-mile increments placing stations near their listed state/metro). Do not invent station names; use opis + city/state from actual CSV sample.
  - `management/commands/geocode_stations.py`:
    CLI flags: --csv path, --all, --limit int, --pacing-seconds float default settings.NOMINATIM_PACING_SECONDS, --dry-run.
    Group by natural_key_hash lat=null, get one row per key.
    If --dry-run → print queries & count; NO DB writes, NO actual Nominatim calls.
    For each query (unique count, limit applies): build normalized address+city+state+USA query. Use settings CachedGeocoder over NominatimGeocoder (auto DB cache). After non-cached calls → time.sleep(pacing_seconds).
    Success: UPDATE all FuelPriceRecord rows WHERE natural_key_hash = hash SET lat, lng, geocoded_at now.
    Failure: log and continue.
    Summary stdout: attempted N unique; succeeded S; reused_preexisting_cache C (not hit Nominatim because GeocodeCache already had them); fresh_nominatim_calls_made F; failed_count J; pacing_seconds value.
- **Acceptance Criteria Addressed**: FR-1, FR-2, FR-3, FR-4, A-5, A-12, AC-1, AC-2
- **Test Requirements**:
  - `rule` TR-7.1 Bad price value "N/A" → import reports invalid with exact unmodified "Invalid Decimal …: 'N/A'" reason; NOT inserted.
  - `rule` TR-7.2 Whitespace collapsed "  Station   Name  " → stored "Station Name".
  - `rule` TR-7.3 Re-import → no duplicates.
  - `rule` TR-7.4 load_demo_fixture → ≥ 150 rows updated non-null coords. Fixture file exists, JSON contains `_provenance.coordinate_type == "approximate_corridor_placements_for_demo_only"` (honest label).
  - `rule` TR-7.5 geocode_stations --all --limit 3 --dry-run with MockGeocoder → 0 writes, 3 queries printed.
  - `rule` TR-7.6 Plan request on 0-coord fresh DB after import → 428.

## Task 8: Automated tests suite offline with all provider mocking; no real Nominatim/OSRM
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 5, Task 6, Task 7
- **Description**:
  - `tests/mocks.py`: MockGeocoder, MockRouter (subclasses of ABCs). call_count public; raise_on sentinel strings trigger ProviderError/Timeout.
  - `tests/conftest.py`: django_db; DEBUG=False; fixtures: small_csv_5rows tmp file, imported_db, demo_fixture_loaded + SQL seed of corridor coords, mocked_providers wrapping caches around mocks so cache_hit paths exercised.
  - `test_import.py`: TR-7.1 strict parse, TR-7.2 whitespace, TR-7.3 idempotent.
  - `test_geocode_command.py`: TR-7.4 fixture load & _provenance label, TR-7.5 pacing/dry-run, TR-7.6 428 after import-only.
  - `test_candidates.py`: TR-4.1-4.5.
  - `test_optimizer.py`: TR-5.1 through TR-5.9 (9 sub-tests covering all AC-4 cases).
  - `test_route_planner.py`: plan_route integration with mocked providers → shape + totals + counters.
  - `test_api.py`: TR-6.1-6.6 (shape & arithmetic incl origin stop flag + total_stops definition), coord input/USA heuristic, provider failure modes (502/504 codes), cache second call, health endpoint, 422 origin catchment failure case.
  - Global offline guard in conftest: optional socket deny or docstring note that Mock* classes do not instantiate httpx Clients so real network cannot happen.
- **Acceptance Criteria Addressed**: FR-15, AC-8
- **Test Requirements**:
  - `rule` TR-8.1 `cd src ; pytest -q` → exit 0.
  - `rule` TR-8.2 pytest collects > 0 tests.
  - `rule` TR-8.3 Optimizer tests do NOT import Nominatim/OSRM provider classes; use pure Python fixture nodes only.

## Task 9: Dockerfile clean no .env copy; CI YAML; .env.example final review
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - `Dockerfile`: python:3.12-slim; WORKDIR /app; ENV PYTHONDONTWRITEBYTECODE PYTHONUNBUFFERED; COPY requirements.txt; pip install no-cache-dir; COPY src ./src; COPY fuel-prices-for-be-assessment.csv ./; COPY .env.example ./.env.example (ONLY as documentation inside image for inspection; NOT as .env active); EXPOSE 8000; WORKDIR /app/src; CMD runserver 0:8000. DELETE any line COPY .env.example .env → .env.
  - `.github/workflows/ci.yml`: ubuntu latest; checkout; python 3.12; pip install; cd src; check; migrate; import_fuel_prices ../fuel-prices-for-be-assessment.csv; load_demo_fixture; pytest tests -q; ruff check ..
  - `.env.example`: double check 9 env vars present from Task 1.5.
- **Acceptance Criteria Addressed**: NFR-10 (user correction #4), AC-13
- **Test Requirements**:
  - `rule` TR-9.1 ci.yml YAML valid.
  - `rule` TR-9.2 Dockerfile grep 'COPY .env.example ./.env$' → 0 matches (fail if present).

## Task 10: Documentation README (16 sections) + LOOM_SCRIPT + IMPLEMENTATION_NOTES; exact consistent language; forbid tank phrases; honest coordinate labels
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6, Task 7
- **Description**:
  - `README.md` 16 sections; ensure consistency throughout:
    Section 1-16 (by prompt list).
    Section 10 Fuel optimization assumptions: A-1, A-2, A-3 verbatim copies from spec. State clearly: stops[0] = origin catchment entry (is_origin_catchment_entry true); total_stops = non-origin stops count, so "a direct route within range has stops.length = 1 with total_stops = 0"; origin_fueled_at_stop_index always null; origin_catchment_station convenience copy provided.
    Section on Duplicate records: A-4 verbatim.
    Section External call count + caching: "Per default plan request with text start+finish: first run = up to 3 external calls (2 Nominatim geocodes of start/finish text + 1 OSRM route). Cached identical repeat request = 0 external calls with ≥ 2 cache hits. Station coordinates never cause Nominatim calls in the request path — always loaded via load_demo_fixture or geocode_stations prep."
    Section 13 Known limitations: heuristic USA bounding-box for coord input, demo corridor approx coordinates not genuine address geocodes, corridor haversine approximation, SQLite concurrency, assessment-only.
    Section 15 Assessment Assumptions: bullets A-1 to A-13 all 13 items verbatim.
    Section 16 Loom Demo Script: link to LOOM_SCRIPT.md.
    Architecture Mermaid sequence diagram: Client → API → RoutePlanner → GeocodeCached → Nominatim (miss) OR GeocodeCache (hit); RoutingCached similarly; DB stations only; Candidates → Optimizer → Response.
  - Phrase grep checks README:
    MUST contain exact strings: segment_consumption_priced_at_departure_stop, load_demo_fixture, python manage.py geocode_stations --all --limit 800 --pacing-seconds 1.0, STATION_COORDINATES_NOT_PREPARED, ORIGIN_CATCHMENT_RADIUS_MILES.
    MUST NOT contain substrings (case-insensitive) unless explicitly discussing what we do NOT do: "full tank", "starts full", "tank capacity", "initial fuel", "city centroid" (if mentioned label as anti-pattern), "polyline" (only negatively).
  - `LOOM_SCRIPT.md`:
    Cover 10 Loom items ≤ 5:15; timings cues; exact commands.
    Step 2 MUST run load_demo_fixture BEFORE runserver. Narration: "We use load_demo_fixture because demo coordinates are approximate corridor placements for quick zero-network Loom; real operators run geocode_stations for address-level accuracy."
    Step 4/5 walk response: "stops[0] is the origin catchment station with is_origin_catchment_entry true; total_stops count excludes origin stops so here total_stops = 2 with stops list length = 3 because we count origin only for pricing". Show cost_model exact string.
    Step 8: Show origin catchment 422 error by using a start not in demo data (e.g., Honolulu if demo fixture has no Hawaii stations).
    Step 9: DP explanation + pytest tests/test_optimizer.py -v shows green cases.
    Step 10: Key assumptions A-1/A-2/A-5/A-6 spoken.
    Grep LOOM_SCRIPT.md "full tank" → 0 occurrences.
  - `IMPLEMENTATION_NOTES.md`: corridor approx accuracy rationale, demo fixture approximate design rationale, Nominatim pacing, DP vs greedy justification, origin catchment rule simplification per feedback.
- **Acceptance Criteria Addressed**: NFR-8, NFR-9, NFR-10, A-1 to A-13 documented, AC-10, AC-12, AC-13
- **Test Requirements**:
  - `rule` TR-10.1 README grep for 16 section headline tokens → ≥ 16 unique headings.
  - `rule` TR-10.2 README grep -i "full tank" → 0 matches.
  - `rule` TR-10.3 README grep exact cost_model string ≥ 3 matches.
  - `rule` TR-10.4 LOOM_SCRIPT grep load_demo_fixture ≥ 1; "origin catchment" ≥ 2; STATION_COORDINATES_NOT_PREPARED ≥ 1; "full tank" 0.
  - `rubric` TR-10.5 Quality; 1-5; threshold ≥ 4.

## Task 11: Final verification gate (run every command from prompt + checklist inspection + report)
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 10 (all prior)
- **Description**:
  - Execute exact 9+2 commands; record stdout/stderr:
    1. python --version
    2. python -m compileall src
    3. cd src ; python manage.py check
    4. cd src ; python manage.py migrate
    5. cd src ; python manage.py import_fuel_prices ../fuel-prices-for-be-assessment.csv
    6. cd src ; python manage.py load_demo_fixture
    7. cd src ; pytest -q
    8. ruff check .
    9. git diff --check
    10. git status --short
  - Diff inspection checklist (manual): no secrets, no hardcoded paths, no hardcoded fake sample response data, no O(N^2) over unfiltered stations lists, no float for prices/gallons/costs, optimizer.py has no retroactive segment pricing (j never > segment start), exceptions all mapped in views, response schema vs README consistent, demo fixture _provenance honest label, Django exact pinned version, no polyline package, forbidden tank phrases all absent.
  - Final report: 1 files changed list, 2 commands+outputs, 3 test results, 4 external API strategy, 5 fuel assumptions recap with exact cost_model + origin catchment rule + origin stop inclusion wording, 6 limitations, 7 suggested git commit message conventional commits format.
- **Acceptance Criteria Addressed**: AC-8, AC-9, AC-13
- **Test Requirements**:
  - `rule` TR-11.1 Commands 1-9 all exit 0.
  - `rule` TR-11.2 Diff checklist all pass (no forbidden patterns).
