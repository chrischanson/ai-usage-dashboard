# Marathon Tracker Plan

> Research project for tracking marathon race dates and registration deadlines worldwide, updating those results periodically, and publishing the latest output as a markdown file.

## Goal

Build a repeatable research pipeline that:

1. Discovers official marathon and half-marathon race pages around the world from authoritative directories.
2. Extracts key dates such as registration open dates, deadlines, lottery dates, qualification dates, and event dates.
3. Re-runs on a schedule so the dataset stays current.
4. Publishes the latest results as a markdown summary committed to the repository.

## Scope

This project is intentionally focused on official sources and durable output.

- Primary source of truth: official race websites, entry pages, and race announcements.
- Secondary assistance: an LLM that interprets page text and normalizes dates. The pipeline checks for `LLM_API_KEY` first. If missing, it will attempt to use local CLIs (`agy --print` or `opencode run`) to run the extraction before falling back to regex.
- Output format: a markdown summary (committed to repo) plus a JSON baseline (internal carry-over, not published).
- Refresh mode: manual runs and scheduled runs.

## Working Model

Each run follows three phases:

### Phase A — Load state + Discover
1. Load the previous run's full output from `docs/marathons.json` (if it exists). This is the
   baseline set of known races with their last extracted data.
2. Load the curated override list from `config/races.json`. For any race whose `id` matches
   a race in the baseline, the curated version replaces it (URLs, dates, etc. take priority).
3. Discover new races from external directories (World Athletics calendar, Wikipedia), merge
   them into the current set. New discoveries that don't already exist in either the baseline
   or the curated list are added with `confidence="low"`.
   *(Note: if a specific `--race-id` is provided, discovery is skipped and only that race is processed).*

### Phase B — Prioritize
4. For every race in the merged set, determine if it needs a fresh fetch:
   - **Targeted Race**: the race ID matches a provided `--race-id` flag (forces a refresh).
   - **Milestone window**: any date field (`event_date`, `registration_open_date`, `registration_deadline`,
     `lottery_deadline`, `qualification_deadline`) falls within the next 90 days.
   - **Missing milestones**: the event date is in the future and any of those five date fields is empty.
   - **Stale data**: the last `extracted_at` timestamp is older than 30 days.
5. Races that meet none of these criteria are **carried over** — their record from the previous
   run's output is kept as-is, with `extraction_method` set to `"carried-over"` and `extracted_at`
   left unchanged.

### Phase C — Refresh
6. For each prioritized race, check if a custom module exists in `marathon_tracker/scrapers/`.
   - If a custom scraper exists (e.g., `london_marathon.py` for `london-marathon`), dynamically execute its `extract()` function to bypass generic extraction.
   - If no custom scraper exists, verify the source URL is still reachable (HTTP HEAD).
     - If the URL returns 4xx/5xx, mark the race with `confidence="low"` and `notes` `"Source URL may be stale; page returned {status}"`. The last known data is preserved.
7. Fetch the official source page for each prioritised race whose URL is reachable (and lacking a custom scraper).
8. Ask the LLM to extract date fields when credentials are available.
9. Fall back to deterministic regex extraction when the LLM is unavailable.
10. Merge the extracted data into a stable result record.
11. Render `docs/marathons.json` (internal baseline, not committed) and `docs/marathons.md` (human-readable summary, committed).

## Data Fields

Each race record should carry:

- `id`
- `name`
- `distance` — one of `marathon`, `half-marathon` (unified model; future distances possible)
- `city`
- `country`
- `region`
- `official_url`
- `registration_url`
- `source_url`
- `event_date`
- `registration_windows` — a list of typed windows (standard, lottery, qualification, charity, invitation), each with `open_date`, `close_date`, `description`, and `official_url`
- `confidence` — one of `high`, `medium`, `low`, `unknown`
- `status` — one of `active`, `carried-over`, `stale`, `new`
- `notes`
- `raw_evidence`
- `extracted_at`
- `extraction_method`

Dates should be stored as ISO 8601 values when a full date is known. If a field is not known with confidence, leave it empty rather than inventing a partial date.

The `distance` field uses a unified model so that marathons and half-marathons coexist in the same tables, filterable by type. The DB schema already has `distance TEXT NOT NULL DEFAULT 'marathon'` on the `races` table.

## Update Strategy

The updater should prefer stable behavior over aggressive guessing.

- Try the race-specific registration or entry page first.
- Fall back to the official race homepage if the first page is missing or broken.
- Use the LLM only as a parser, not as a source of facts.
- Record evidence snippets so extracted dates remain auditable.
- Mark uncertain records clearly in the generated output.

## Publishing Strategy

The output is committed directly to the repository — no separate deployment step.

- `docs/marathons.md` is the human-readable summary (committed, visible on GitHub).
- `docs/marathons.db` is the SQLite database (internal carry-over baseline).
- `docs/index.html` is the polished web page (GitHub Pages now, standalone domain later).
- The update runs daily via `run_update.sh` and can also be triggered manually.
- If an `LLM_API_KEY` is available, the pipeline extracts richer data.

### Confidence-Gated Publishing

The published output (`docs/marathons.md` and `docs/index.html`) only includes races with **medium or high confidence**. Low-confidence and unknown-confidence races remain in `docs/marathons.db` for future verification but are excluded from public-facing pages. This ensures the running community sees accurate, reliable data while the discovery pipeline can cast a wide net.

The render module applies this gate:
- Races with `confidence` of `"low"` or `"unknown"` are excluded from `render_markdown()` output.
- The total count in the header reflects only published (medium+) races.
- The DB retains all races regardless of confidence for audit and future promotion.

## Job Design

The single workflow job orchestrates all three phases:

```
daily run:
  1. load previous output from docs/marathons.json (baseline)
  2. load curated override from config/races.json
  3. discover new races from external directories
  4. merge: curated overrides baseline, new discoveries appended
  5. for each race in the merged set:
     a. decide if it needs refresh (milestone window / missing milestones / stale)
     b. if yes: verify source URL is reachable
        - reachable:   fetch page → extract dates (LLM or regex) → status=active
        - unreachable: keep last known data, status=stale, confidence=low
     c. if no: carry over from previous output unchanged, status=carried-over
   6. render docs/marathons.json (internal baseline) and docs/marathons.md (summary)
   7. commit docs/marathons.md to the repository

Key invariants:
- A race is never removed from the output once added — only marked stale or carried-over.
- The curated list always overrides auto-discovered/same-id races.
- `config/races.json` only gets new races appended — never pruned or overwritten.
- `docs/marathons.json` is the internal carry-over baseline for the next run (gitignored).
- `docs/marathons.md` is the published summary (committed to git).

## Milestones

### 1. Seed the race list

Populate `config/races.json` with representative races across regions:

- North America
- Europe
- Asia
- Oceania
- Africa
- South America

This gives the tracker enough variety to validate the extraction and rendering path early.

### 2. Build the fetch and extract path

Implement a fetcher that can read official pages and a parser that can interpret the content.

Acceptance criteria:

- The updater runs locally without crashing.
- The updater can run without an LLM.
- The updater can use an LLM when credentials exist.

### 3. Render static outputs

Generate a markdown summary and a structured JSON dataset.

Acceptance criteria:

- `docs/marathons.md` renders as a readable table on GitHub.
- `docs/marathons.json` validates as JSON.
- The markdown file shows the current records with their dates, confidence, and status.

### 4. Commit results via CI

Add a workflow that updates the output in CI.

Acceptance criteria:

- The workflow runs on schedule.
- The workflow can be run manually.
- The generated `docs/marathons.md` is committed to the repository.

### 5. Automatically discover new races

The pipeline must not rely solely on the static seed list. New races should be discovered
from authoritative external sources so the dataset grows without manual curation.

Acceptance criteria:

- The updater can read external race directories (e.g. Wikipedia list of marathons, World
  Athletics calendar) and extract candidate race metadata.
- Candidate races are merged with the existing curated list, deduplicating by URL or name.
- New races get fetched and added to the output automatically on each run.
- The curated list in `config/races.json` remains as an override / supplement: races there
  are always included, and their URLs take priority.

#### 5.1 Design

**New module: `discover.py`**

Add `research/marathon_tracker/marathon_tracker/discover.py` with two source scrapers
and a merge function.

---

**Source A — World Athletics Label Races calendar (primary)**

- URL: `https://worldathletics.org/competitions/world-athletics-label-road-races/calendar-results`
- WA renders its calendar via a Next.js client-side app. The underlying data is served by
  their internal GraphQL API at `https://analytics-api.worldathletics.org`.
- The Python package `worldathletics` (PyPI) wraps this API but adds an external dependency.
  Instead, `discover.py` will send a raw GraphQL query using the built-in `urllib` module
  (no new dependency).
- Query filters: competition group = label road races, season = current year, discipline =
  marathon, event distance = 42.195 km.
- The response includes: competition name, venue city, country code, start date, competition
  subgroup (Platinum/Gold/Elite/Label).
- If the GraphQL endpoint changes or is unreachable, fall back to parsing the WA calendar
  HTML page's table markup (Next.js renders a `<table>` with class `calendarTable`).

Extracted fields per race:
| Field | Source |
|---|---|
| `name` | competition.name |
| `city` | venue.city |
| `country` | venue.countryCode → mapped to full name |
| `event_date` | competition.startDate (ISO 8601) |
| `official_url` | not available from WA — left empty for pipeline fetch |
| `confidence` | always `"low"` for auto-discovered races (need verification) |
| `notes` | `"Auto-discovered from World Athletics calendar"` |

---

**Source B — Wikipedia "List of World Athletics Label marathon races" (secondary)**

- URL: `https://en.wikipedia.org/wiki/List_of_World_Athletics_Label_marathon_races`
- Fetched via the Wikipedia REST API:
  `GET https://en.wikipedia.org/w/api.php?action=parse&page=List_of_World_Athletics_Label_marathon_races&prop=text&format=json`
- Parse the `<table>` elements to extract rows with columns: Name, City, Country, Month.
- This source is less current (the page has a stale-data warning) but provides races WA's
  filtered calendar might miss.
- Extracted `name`, `city`, `country`, approximate `month`. No exact event date or URL.
- Used only when the WA source returns zero results.

---

**Merge strategy (`discover.merge_races`)**

```
def merge_races(
    curated: list[Race],
    discovered: list[RaceCandidate],
) -> list[Race]:
```

1. Build a lookup key from curated races: `(name.lower(), city.lower())` and
   `(official_url or registration_url)`.
2. For each candidate, skip if the lookup key matches an existing curated race.
3. Assign an `id` from candidate name (slugify: lowercase, replace spaces with hyphens,
   strip non-alphanumeric except hyphens).
4. Add candidate as a new `Race` with `confidence="low"` and
   `notes="Auto-discovered from <source>; dates need verification"`.
5. Always include all curated races first, then append the new discoveries.
6. Log the count of skipped (duplicate) and newly added races.

---

**Integration into `update.py`**

```
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    curated = load_races(args.config)

    # New: also discover from WA / Wikipedia
    discovered = discover_races()          # returns list[RaceCandidate]
    races = merge_races(curated, discovered)

    # ... existing fetch/extract/render loop ...
```

New CLI flags:
| Flag | Default | Description |
|---|---|---|
| `--discover` | `true` | Enable auto-discovery of new races |
| `--no-discover` | `false` | Disable auto-discovery (use curated list only) |
| `--discover-source` | `"world-athletics"` | Source to use: `world-athletics`, `wikipedia`, or `all` |
| `--race-id` | `None` | Update only a specific race ID, bypassing discovery |

The workflow in `.github/workflows/marathon-tracker.yml` runs with defaults (auto-discovery
on, WA source). Users running locally with `--no-network` also get `--no-discover` implied.

---

**New CLI flags on `update.py`**

```
parser.add_argument("--discover", action=argparse.BooleanOptionalAction, default=True)
parser.add_argument("--discover-source", choices=["world-athletics", "wikipedia", "all"],
                    default="world-athletics")
```

`--no-network` implies `--no-discover` (no point discovering if pages can't be fetched).

---

**Caching**

Newly discovered races are appended to `config/races.json` automatically so they
persist across runs and can have their URLs filled in by a future manual pass.
The file is never pruned — races are only ever added, never removed.

### 6. Keep the data fresh

As race sites change, the tracker should continue to update records rather than freezing them.

Acceptance criteria:

- New dates can be added without changing the code.
- Broken source URLs do not stop the entire update run — the race stays in the output with
  `confidence="low"` and the last known data preserved.
- The latest data remains visible on the published page.

#### 6.1 Refresh prioritisation

Not all races need to be fetched on every run. The job decides per race:

| Condition | Action |
|---|---|
| Any date field is within 90 days of today | **Fetch** — milestones are approaching |
| Event date is in the future & any date field is empty | **Fetch** — data is incomplete |
| `extracted_at` is more than 30 days old | **Fetch** — data is stale |
| None of the above | **Skip** — carry over previous output |

This avoids unnecessary fetches for races whose events are far in the future and whose
dates are already fully populated.

#### 6.2 Source URL verification

Before fetching, the updater sends an HTTP HEAD request to `source_url` (or `official_url`
as fallback). If the response is 4xx or 5xx:

- The race is **not** fetched.
- The race remains in the output with its last known data.
- `confidence` is downgraded to `"low"`.
- `notes` is updated with the HTTP status code and a hint that the source may be stale.

This prevents a transient server error from wiping out good data while still flagging
broken pages for manual review.

## Risks

- Race sites change URLs frequently.
- Some pages block or redirect automated fetches.
- Date text may be ambiguous unless the source page is carefully chosen.
- LLM output is only as good as the page text provided to it.
- World Athletics may change their GraphQL schema or require authentication without notice,
  breaking the auto-discovery source until the query is updated.

## Operating Rules

- Prefer official pages over third-party aggregation.
- Prefer explicit dates over inferred dates.
- Prefer a missing field over a questionable field.
- Keep the output easy to audit and easy to refresh.

## Current State

The core update pipeline is fully migrated to a relational SQLite backend and supports modular scrapers. The repo contains:

- A relational SQLite database at `docs/marathons.db` containing `races`, `race_events`, and `extraction_metadata` tables.
- The update pipeline in `marathon_tracker/` using SQLite (`config.py`, `db.py`, `update.py`).
- A modular scraper architecture in `marathon_tracker/scrapers/` to allow per-marathon extraction scripts.
- Rendered static output in `docs/marathons.md` (generated directly from the SQLite database).
- A devserver execution wrapper script `run_update.sh` for manual or cron execution (with `.github/workflows/` removed).

## Next Phase (v2 Roadmap)

Now that the core tracker is stable, the next useful work is to expand its scope and coverage.

**Design decisions** (resolved via grill-me sessions 2026-06-21):

| Decision | Answer |
|---|---|
| **Audience** | Public-facing resource for the running community |
| **Primary output** | GitHub Pages now → standalone site later |
| **Coverage** | Every marathon/half-marathon discoverable worldwide |
| **Quality vs. breadth** | Accuracy first — prefer missing over wrong |
| **Publication gate** | Only medium/high confidence races published; low stays in DB |
| **Half-marathon model** | Unified model with parent `races` and child `race_offerings` (distances) |
| **Location granularity** | Added `state_province` column to `locations` |
| **URL normalization** | Normalized `official_url` and `registration_url` in `races` to FKs in `official_urls` |
| **Update cadence** | Daily with smart prioritization |

**Priority order:**

1. **Database Refactoring & Normalization** (Task 1 - essential foundation)
2. **Half-Marathon Discovery** (Task 2)
3. **Pipeline & Rendering Integration** (Task 3)
4. **Confidence-Gated Publishing** (Task 4)
5. **Expand Auto-Discovery Sources** (Task 5 - future)
6. **Extraction Robustness** (Task 6 - future)

---

### Task 1: Database Refactoring & Normalization

**Scope**: Refactor the database schema in `db.py` to support normalized locations, normalized URLs, and the parent-child `races` -> `race_offerings` model. Implement a robust migration inside `db.py` to upgrade the existing database without losing data, and update python dataclasses/mappings.

#### Fully Normalized & Deduplicated DDL Schema

```sql
CREATE TABLE IF NOT EXISTS regions (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS countries (
    name TEXT PRIMARY KEY,
    region_name TEXT NOT NULL,
    FOREIGN KEY(region_name) REFERENCES regions(name)
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    state_province TEXT, -- Subdivision field
    country_name TEXT NOT NULL,
    FOREIGN KEY(country_name) REFERENCES countries(name),
    UNIQUE(city, state_province, country_name)
);

CREATE TABLE IF NOT EXISTS official_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS races (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location_id INTEGER NOT NULL,
    official_url_id INTEGER NOT NULL, -- The main website for the race
    FOREIGN KEY(location_id) REFERENCES locations(id),
    FOREIGN KEY(official_url_id) REFERENCES official_urls(id)
);

CREATE TABLE IF NOT EXISTS race_offerings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id TEXT NOT NULL,
    distance TEXT NOT NULL, -- 'marathon', 'half-marathon', etc.
    FOREIGN KEY(race_id) REFERENCES races(id),
    UNIQUE(race_id, distance)
);

CREATE TABLE IF NOT EXISTS event_statuses (
    status TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS race_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_offering_id INTEGER NOT NULL, -- References offering instead of parent race
    event_date TEXT,                    -- ISO 8601 format or NULL if TBD
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY(race_offering_id) REFERENCES race_offerings(id),
    FOREIGN KEY(status) REFERENCES event_statuses(status),
    UNIQUE(race_offering_id, event_date)
);

CREATE TABLE IF NOT EXISTS registration_types (
    type TEXT PRIMARY KEY,
    default_description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registration_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    window_type TEXT NOT NULL,
    description TEXT,                  -- Optional override; NULL defaults to registration_types.default_description
    open_date TEXT,                    -- ISO 8601 format
    close_date TEXT,                   -- ISO 8601 format
    official_url_id INTEGER,
    FOREIGN KEY(event_id) REFERENCES race_events(id),
    FOREIGN KEY(window_type) REFERENCES registration_types(type),
    FOREIGN KEY(official_url_id) REFERENCES official_urls(id),
    UNIQUE(event_id, window_type, open_date, close_date)
);
```

#### Database Migration Steps (in `init_db`)
1. **Regions & Countries Migration**:
   - Create `regions` and `countries` tables.
   - Seed them with known region/country pairs derived from the existing dataset and mapping dictionaries in python.
2. **Locations Migration**:
   - Rename `locations` to `locations_old`.
   - Create new `locations` table (without `region` column, referencing `countries.name`).
   - Populate from `locations_old` (mapping `country` names, dropping `region`).
   - Drop `locations_old`.
3. **URL Normalization**:
   - Insert all unique URL strings from legacy `races` (`official_url` and `registration_url`) into `official_urls`.
4. **Races Table Normalization**:
   - Rename `races` to `races_old`.
   - Create new `races` table (using `official_url_id`, dropping the redundant `registration_url_id` which is already stored on `registration_windows`).
   - Populate by mapping `official_url` to its ID in `official_urls`.
5. **Race Offerings Creation**:
   - Create the `race_offerings` table.
   - Insert entries from `races_old` (`id` -> `race_id`, `distance` -> `distance`).
6. **Race Events Migration**:
   - Rename `race_events` to `race_events_old`.
   - Create new `race_events` table (removing `year` column, referencing `race_offering_id`).
   - Populate by joining `race_events_old` with `race_offerings` on `race_id` to map.
   - Drop `race_events_old` and `races_old`.
7. **Registration Types & Windows**:
   - Create `registration_types` and seed standard values.
   - Update `registration_windows` to make `description` nullable/optional, saving space when it matches the default description.
8. **Trigger Updates**:
   - Recreate all SQL triggers for `change_log` to log inserts/updates/deletes on the newly normalized tables.

#### Files to modify:

#### [MODIFY] `marathon_tracker/db.py`
- Rewrite `init_db()` to implement the schema and migration steps.
- Update all SQL triggers for `change_log` to log inserts/updates/deletes on new tables.

#### [MODIFY] `marathon_tracker/models.py`
- Update `Race` to include `state_province` and have `distance` removed (distance becomes part of `RaceResult` / `race_offerings`).
- Update `RaceResult` to hold `distance` and `state_province`.
- Update serialization helpers (`from_dict`, `to_dict`).

#### [MODIFY] `marathon_tracker/config.py`
- Update `load_races()` to retrieve normalized location state, URLs, and offerings.
- Update `load_previous_output()` to fetch events joined with `race_offerings`.
- Update `save_races()` and `save_race_results()` to resolve URLs via `official_urls` and map properties correctly to normalized tables.

**Estimated size**: ~4K tokens of code changes.

---

### Task 2: Half-Marathon Tracking — Discovery

**Scope**: Update the discovery module to find half-marathons from World Athletics and Wikipedia.

**Files to modify:**

#### [MODIFY] `marathon_tracker/discover.py`
- Update `discover_from_world_athletics()` to query for half-marathon distances in addition to marathon. The WA GraphQL API filters by discipline/distance; add a second query pass for half-marathon events (42.195 km → also 21.0975 km), or broaden the competition group filter.
- Add a `distance` field to discovered `Race` objects. Parse the competition name or subgroup to infer `"marathon"` vs `"half-marathon"`. Default to `"marathon"` if ambiguous.
- Update `discover_from_wikipedia()` to also parse half-marathon tables if available. The current Wikipedia source is specifically about "Label marathon races" — add a secondary page `List_of_World_Athletics_Label_half_marathon_races` if it exists.
- Update `merge_races()` to consider `distance` as part of the dedup key. Two races with the same name/city but different distances should not be deduplicated (e.g., "Tokyo Marathon" and "Tokyo Half Marathon").

**Estimated size**: ~3K tokens of code changes.

---

### Task 3: Half-Marathon Tracking — Pipeline & Render

**Scope**: Thread `distance` through the update pipeline and render output.

**Files to modify:**

#### [MODIFY] `marathon_tracker/update.py`
- No structural changes needed — `distance` flows through `Race` → `RaceResult` naturally once the model is updated.
- Update print/log messages to include distance for clarity.

#### [MODIFY] `marathon_tracker/render.py`
- Add a `Distance` column to the markdown table.
- Update `render_markdown()` to display the distance ("Marathon" / "Half Marathon") in each row.
- The `index.html` generator should add a distance filter control.

#### [MODIFY] `marathon_tracker/extract.py`
- Update LLM prompt to also extract distance/race type from page text if not already known.
- If the LLM detects the page is about a half-marathon, set `distance = "half-marathon"` on the result.

**Estimated size**: ~2K tokens of code changes.

---

### Task 4: Confidence-Gated Publishing

**Scope**: Filter the published output to only show medium/high confidence races.

**Files to modify:**

#### [MODIFY] `marathon_tracker/render.py`
- In `write_outputs()`, filter `results` to only include records where `confidence` is `"medium"` or `"high"` before rendering markdown.
- Update the header count to reflect the filtered total.
- Add a note in the markdown footer: "*Only races with medium or high confidence are shown. See the database for all tracked races.*"

#### [MODIFY] `marathon_tracker/update.py`
- No changes needed — the DB always receives all results. Filtering is render-only.

**Estimated size**: ~500 tokens of code changes.

---

### Task 5: Expand Auto-Discovery Sources (future)

**Scope**: Integrate new external directories to expand coverage beyond World Athletics.

Prioritized sources:
- AIMS (Association of International Marathons and Distance Races) calendar
- MarathonGuide.com
- Registration platforms like RunSignup and Active.com

This task is deferred until half-marathon tracking and confidence gating are stable.

---

### Task 6: Extraction Robustness (future)

**Scope**: Continue relying on lightweight HTTP requests and LLM extraction, maintaining current strategies until significant bot-protection roadblocks necessitate headless browsers or third-party scraping APIs.

This task is deferred — no code changes until a specific extraction failure pattern emerges.

---

## Test Plan

All tests use the standard library `unittest` framework. Run with:

```bash
PYTHONPATH=research/marathon_tracker python3 -m unittest discover -s research/marathon_tracker/tests
```

### Existing Tests (baseline — must continue passing)

| Test file | What it covers |
|---|---|
| `tests/test_extract.py` | Date normalization, regex extraction of event dates and registration windows |
| `tests/test_fetch.py` | URL reachability checks, page text fetching |
| `tests/test_llm.py` | LLM extraction prompt/response parsing, fallback behavior |
| `tests/test_discover.py` | World Athletics GraphQL parsing, Wikipedia table parsing, merge logic |
| `tests/test_triggers.py` | SQLite change_log triggers for INSERT/UPDATE/DELETE on all tables |

### New Tests for v2

#### `tests/test_models_distance.py` (Task 1)

| Test case | Description |
|---|---|
| `test_race_default_distance` | `Race()` without explicit `distance` defaults to `"marathon"` |
| `test_race_half_marathon_distance` | `Race(distance="half-marathon")` round-trips through `from_dict()`/`to_dict()` |
| `test_race_result_from_race_copies_distance` | `RaceResult.from_race(race)` preserves the `distance` field |
| `test_race_result_to_dict_includes_distance` | `to_dict()` output includes `"distance"` key |
| `test_race_from_dict_missing_distance` | `from_dict()` with no `distance` key defaults to `"marathon"` |

#### `tests/test_discover_half.py` (Task 2)

| Test case | Description |
|---|---|
| `test_wa_half_marathon_discovery` | Mock WA GraphQL response with half-marathon competitions → produces `Race` objects with `distance="half-marathon"` |
| `test_wa_mixed_distances` | Mock response with both marathon and half-marathon entries → both distances appear in output |
| `test_merge_same_name_different_distance` | `merge_races()` does NOT deduplicate "Tokyo Marathon" and "Tokyo Half Marathon" |
| `test_merge_same_name_same_distance` | `merge_races()` DOES deduplicate two entries with identical name+city+distance |
| `test_wikipedia_half_marathon_table` | Mock Wikipedia HTML for half-marathon page → produces `Race` objects with `distance="half-marathon"` |

#### `tests/test_config_distance.py` (Task 1)

| Test case | Description |
|---|---|
| `test_load_races_includes_distance` | Insert a race with `distance='half-marathon'` into SQLite → `load_races()` returns `Race` with correct `distance` |
| `test_save_races_persists_distance` | `save_races()` with a `Race(distance="half-marathon")` → query DB confirms `distance='half-marathon'` |
| `test_load_previous_output_includes_distance` | Full round-trip: save a `RaceResult` with `distance='half-marathon'` → `load_previous_output()` returns it with correct `distance` |

#### `tests/test_render_confidence.py` (Task 4)

| Test case | Description |
|---|---|
| `test_render_excludes_low_confidence` | `render_markdown()` with a mix of confidence levels → low/unknown races are absent from output |
| `test_render_includes_medium_confidence` | `render_markdown()` with `confidence="medium"` race → race appears in output |
| `test_render_includes_high_confidence` | `render_markdown()` with `confidence="high"` race → race appears in output |
| `test_render_count_reflects_filtered` | Header count matches the number of medium+ confidence races, not total |
| `test_render_footer_note` | Output contains a note about additional races in the database |

#### `tests/test_render_distance.py` (Task 3)

| Test case | Description |
|---|---|
| `test_render_shows_distance_column` | Markdown table header includes "Distance" column |
| `test_render_marathon_label` | Race with `distance="marathon"` renders as "Marathon" in the table |
| `test_render_half_marathon_label` | Race with `distance="half-marathon"` renders as "Half Marathon" in the table |

### Verification Commands

After each task, run:

```bash
# Unit tests
PYTHONPATH=research/marathon_tracker python3 -m unittest discover -s research/marathon_tracker/tests

# Offline pipeline smoke test (no network, no LLM)
python3 -m marathon_tracker.update --no-network --db docs/marathons.db --docs-dir docs/

# Verify rendered output is valid markdown
head -20 research/marathon_tracker/docs/marathons.md
```
