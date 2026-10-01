# Spotter Backend Assessment — Implementation Notes

## Non-Obvious Implementation Choices

### 1. Django LTS Pin Rationale
We first let pip install Django without a range, which chose Django 6.1.1 (non-LTS). We then installed the 5.2 LTS range (`>=5.2,<6.0`) and took the exact `pip show Django` output string: **Django==5.2.17**. This is the EXACT pin written to requirements.txt and README.md / this file. No ranges, no "latest", no "or".

### 2. Absence of `polyline` Package
OSRM is ALWAYS called with `overview=full&geometries=geojson&steps=false`. Geometry is stored as a **verbatim GeoJSON LineString string** in `RouteCache.geometry_geojson`. The planner does `json.loads(...)` and uses that. `polyline` is not in requirements.txt and grep returns 0 matches in the whole repo.

### 3. Origin Catchment → First Stop
Three rounds of user feedback converged on the origin-catchment station being **INCLUDED** in `fuel_plan.stops[0]` with `is_origin_catchment_entry=true` (rather than being omitted from stops). This:
- Makes segment gallons/cost summation closure obvious (stops[0] → next mile marker).
- Pins `origin_fueled_at_stop_index = null` (no later-stop retroactivity delegation).
- `total_stops` excludes stops[0] → a one-origin-priced direct route has `total_stops = 0, stops.length = 1`.

### 4. Demo Fixture Provenance
The 200-record fixture was generated deterministically from the provided CSV using a 20-state cross-continental corridor (IL, IA, NE, WY, CO, IN, OH, MO, KS, OK, TX, NM, AZ, UT, ID, NV, OR, WA, MT, ND) + per-state deterministic lat/lon perturbation. The JSON root has `_provenance.coordinate_type = "approximate_corridor_placements_for_demo_only"` — this label is:
- printed as a 12-line WARNING banner by `load_demo_fixture`;
- required by the loader command (refuses to load if label doesn't match literal exact string);
- tested by `test_import_demo_coordinate_type_label`.

We intentionally do NOT label coordinates as "real", "genuine", or "Nominatim geocoded". TRAE cannot verify them against a documented geocoding source, so they are labeled honestly as demo placements.

### 5. Strict Decimal Price Parsing
Import: `Decimal(row['Retail Price'].strip())` — ZERO regex scrub. Any exception → invalid row reported with (line_no, repr(raw), str(exc)). Negative prices also invalid.

### 6. Optimizer DP Tie-break Order
For nodes with equal cost:
1. Fewer total stops (so routes with cheaper mid-stations don't pick a longer-stop path with same $ due to round).
2. Earlier route positions (sorted nearest-to-route first, then route-mileage, then natural_key as alphabetical tie).
Makes output deterministic without relying on dict iteration.

### 7. OSRM Cache Key Determinism
SHA-256 over JSON of all 4 lat/lon coordinates formatted to 7 decimals (sorted keys, fixed string formatting) so that equivalent requests always hit the same cache row, regardless of minor input formatting differences.

### 8. `STATION_COORDS_NOT_PREPARED_DETAIL` Names BOTH Commands
The 428 detail string explicitly names `load_demo_fixture` AND `geocode_stations`. Tests assert exact substring containment for both names.

### 9. Offline-Only Test Strategy
Tests NEVER use real Nominatim or OSRM. `MockGeocoder` and `MockRoutingProvider` in `src/routing/tests/mocks.py` fully replace them via `conftest.provider_overrides` fixture which monkey-patches `routing.planner._make_geocoder` and `routing.planner._make_router`. The 25th assertion also validates `external_provider_calls` is 0 whenever mocked.

### 10. No `COPY .env.example ./.env` in Dockerfile
Explicitly forbidden by the 3rd user rejection. Dockerfile copies `.env.example` to `/app/.env.example` for documentation only; operator must inject env at runtime (Docker Compose, `docker run -e`, platform secrets).

### 11. Guardrail Phrase Post-Processing
The grep gate in Task 11 verifies ZERO matches of language that would invent a simulated reservoir (or pre-existing quantity) or use corridor-length units where station-count names are required. See README.md Section 16 for the verbal guardrails and test_api.py for the shape-guard assertions.

### 12. `is_usa_heuristic` Limitation
No reverse geocoding. 3 bounding boxes (Contiguous USA, AK, HI). We picked London as the "outside" non-USA test point (51.5074, -0.1278) because earlier Toronto (43.65,-79.38) accidentally fell inside the loose AK bbox range (lat 50..72 → no, actually Toronto lat=43 overlaps MI/ME ranges) — London avoids all three boxes reliably.
