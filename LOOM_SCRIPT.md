# Spotter Backend Assessment Loom Demo Script

Total run time target: ≤5:15 (10 steps, each with time budget below).
Narrator voice: calm, structured, honest about demo fixture provenance, uses `cost_model` exact phrase.

---

**Step 1 — Intro (0:00 → 0:25, 25 s)**
- Repo: Django 5.2.17 LTS, requirements.txt 21 exact pins, no polyline package.
- Deliverables list: endpoints (plan + health), 3 management commands, pytest offline suite (25 tests), CI/Docker.

**Step 2 — Data Prep: Import + Load Demo Fixture (0:25 → 1:00, 35 s)**
- Run `cd src`.
- Run `python manage.py migrate --noinput`. (keep silent if already migrated)
- Run `python manage.py import_fuel_prices ../prompts/fuel-prices-for-be-assessment.csv` → show counts ~8,151 rows imported + strict-Decimal invalid reporting.
- **[Honest provenance speech]** Run `python manage.py load_demo_fixture`. *Narration:* "This loads the 200-record demo fixture. The coordinates are labeled by the fixture itself as `approximate_corridor_placements_for_demo_only` — they are not Nominatim address-level geocodes, they are not city centroids, they are deterministic approximate corridor placements meant strictly for this assessment demo. The 428 error (shown later) requires EITHER this fixture OR the operator to run `geocode_stations` before planning routes." Mention the 12-line yellow banner that the command prints.
- `stations_with_coordinates` becomes 200.

**Step 3 — Cost Model + API Shape on README (1:00 → 1:35, 35 s)**
- Open README.md Section 7 Fuel Cost Model. Point to `cost_model = "segment_consumption_priced_at_departure_stop"`.
- Emphasize total_gallons_consumed (Σ stops.segment_gallons_consumed INCLUDING stops[0] origin entry; origin catchment is stops[0] with flag true; total_stops counts NON-origin entries only).
- Open Section 8 Origin Catchment Rule. Say: "No synthetic fuel is ever invented; origin 5-mile catchment is strict. Failures we'll demo in Step 8 produce the exact HTTP 422 detail string."
- Open Section 15 Assumptions A-1..A-13 VERBATIM copy.

**Step 4 — Lint & Tests (1:35 → 2:15, 40 s)**
- Run `cd ..` then `ruff check src` → **All checks passed!** 0 errors.
- Run `python -m pytest -q src/routing/tests` → 25 passed, 0 warnings. 0 real Nominatim/OSRM calls. Mention the 9 optimizer cases (direct/one-stop/multi-stop/infeasible/origin-422/no-retro/gallons-Σ/cost-Σ/total_stops-count).

**Step 5 — Run Server (2:15 → 2:25, 10 s)**
- Run `cd src && python manage.py runserver 127.0.0.1:8000` (background it or run in another tab; show running).

**Step 6 — Health Check + 428 Guard (2:25 → 2:55, 30 s)**
- Run `curl -s http://127.0.0.1:8000/api/v1/health/` → `{"status":"ok"}`.
- [Optional — skip if already loaded, else temporarily start fresh to show the empty-DB guard.] In a fresh DB state curl plan → HTTP **428** `STATION_COORDINATES_NOT_PREPARED` detail naming **BOTH** `load_demo_fixture` **AND** `geocode_stations`.

**Step 7 — Full Chicago → Denver Plan (2:55 → 3:55, 60 s)**
- Run POST plan request Chicago→Denver via raw-coords OR text (nominatim text only if available; prefer raw coords 41.8818/-87.6232 to 39.7392/-104.9903 for offline-safety).
- Show the 200 response shape:
  - `estimated_fuel_consumed_gallons = route_distance / 10`
  - `fuel_plan.cost_model = "segment_consumption_priced_at_departure_stop"` (exact)
  - `stops[0].is_origin_catchment_entry = true` (highlight origin entry included as first stop)
  - `fuel_plan.total_gallons_consumed == Σ stops.segment_gallons_consumed INCLUDING stops[0]` (say the numbers match)
  - `fuel_plan.total_cost == Σ stops.segment_cost INCLUDING stops[0]`
  - `total_stops = len(stops) − 1` (non-origin only)
  - `origin_fueled_at_stop_index = null` (always)
  - 6 exact `data_quality` keys (no corridor-length misnomer as a station-count; only precise names used)
  - `assumptions.A_3_cost_model_segment_departure_price` present
  - `route.geometry.type = "LineString"` coordinates in GeoJSON [lon,lat] order — no polyline package.

**Step 8 — HTTP 422 Origin-Catchment Demo (3:55 → 4:25, 30 s) — REQUIRED per tasks.md**
- Construct a clearly bad route: origin at a point far from any demo-fixture station (e.g. pick Portland, OR or Miami, FL coords that have NO nearby demo-station with coordinates). Use raw `{lat/lon}`.
- Run curl POST, capture HTTP code → **422** with exact `NO_FEASIBLE_FUEL_PLAN` + `"No fuel station with coordinates is available near the route origin under the configured origin catchment radius."` (detail literal).
- Note: we would rather fail loudly here than invent a synthetic origin price.

**Step 9 — USA Validation 400 (4:25 → 4:50, 25 s)**
- POST with start={51.5074,-0.1278} (London) → HTTP **400** `USA_VALIDATION_FAILED` 400 status with code+detail JSON body.
- Caller can then either: pass a US coordinate; or use a string like `"London, OH"` (which is in the US) to pass the heuristic.

**Step 10 — Closing (4:50 → ≤5:15, ≤25 s)**
- Recap: Django LTS 5.2.17 exact pin, 25 pytest tests offline, no polyline lib, demo fixture honestly labeled, cost_model exact string invariant everywhere, all HTTP status codes and exact detail strings match spec.
- Files: README.md (16 sections, Section 15 VERBATIM A-1..A-13), LOOM_SCRIPT.md (this), IMPLEMENTATION_NOTES.md, .github/workflows/ci.yml, Dockerfile.
- Suggested next steps: run `Task 11` verification gate (9 commands one-release).

---

Budget check: 25+35+35+40+10+30+60+30+25+25 = **315 s = 5:15**. On target.
