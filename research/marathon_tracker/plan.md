# Marathon Tracker Plan

> Research project for tracking marathon race dates and registration deadlines worldwide, updating those results periodically, and publishing the latest output to GitHub Pages.

## Goal

Build a repeatable research pipeline that:

1. Discovers official marathon race pages around the world from authoritative directories.
2. Extracts key dates such as registration open dates, deadlines, lottery dates, qualification dates, and event dates.
3. Re-runs on a schedule so the dataset stays current.
4. Publishes the latest results as a static GitHub Pages site.

## Scope

This project is intentionally focused on official sources and durable output.

- Primary source of truth: official race websites, entry pages, and race announcements.
- Secondary assistance: an LLM that interprets page text and normalizes dates.
- Output format: static JSON plus a readable HTML page.
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

### Phase B — Prioritize
4. For every race in the merged set, determine if it needs a fresh fetch:
   - **Milestone window**: any date field (`event_date`, `registration_open_date`, `registration_deadline`,
     `lottery_deadline`, `qualification_deadline`) falls within the next 90 days.
   - **Missing milestones**: the event date is in the future and any of those five date fields is empty.
   - **Stale data**: the last `extracted_at` timestamp is older than 30 days.
5. Races that meet none of these criteria are **carried over** — their record from the previous
   run's output is kept as-is, with `extraction_method` set to `"carried-over"` and `extracted_at`
   left unchanged.

### Phase C — Refresh
6. For each prioritized race, verify the source URL is still reachable (HTTP HEAD).
   - If the URL returns 4xx/5xx, mark the race with `confidence="low"` and `notes`
     `"Source URL may be stale; page returned {status}"`. The last known data is preserved.
7. Fetch the official source page for each prioritised race whose URL is reachable.
8. Ask the LLM to extract date fields when credentials are available.
9. Fall back to deterministic regex extraction when the LLM is unavailable.
10. Merge the extracted data into a stable result record.
11. Render `docs/marathons.json` and `docs/index.html`.
12. Publish `docs/` through GitHub Pages.

## Data Fields

Each race record should carry:

- `id`
- `name`
- `city`
- `country`
- `region`
- `official_url`
- `registration_url`
- `source_url`
- `event_date`
- `registration_open_date`
- `registration_deadline`
- `lottery_deadline`
- `qualification_deadline`
- `confidence`
- `status` — one of `active`, `carried-over`, `stale`, `new`
- `notes`
- `raw_evidence`
- `extracted_at`
- `extraction_method`

Dates should be stored as ISO 8601 values when a full date is known. If a field is not known with confidence, leave it empty rather than inventing a partial date.

## Update Strategy

The updater should prefer stable behavior over aggressive guessing.

- Try the race-specific registration or entry page first.
- Fall back to the official race homepage if the first page is missing or broken.
- Use the LLM only as a parser, not as a source of facts.
- Record evidence snippets so extracted dates remain auditable.
- Mark uncertain records clearly in the generated output.

## Publishing Strategy

GitHub Pages is the distribution target.

- `docs/` is the publish directory.
- `docs/index.html` is the human-facing landing page.
- `docs/marathons.json` is the machine-readable dataset.
- The GitHub Actions workflow runs daily and can also be triggered manually.
- If the repo has an `LLM_API_KEY` secret, the workflow can extract richer data in CI.

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
  6. render docs/marathons.json and docs/index.html
  7. commit docs/ and deploy to GitHub Pages

Key invariants:
- A race is never removed from the output once added — only marked stale or carried-over.
- The curated list always overrides auto-discovered/same-id races.
- `config/races.json` only gets new races appended — never pruned or overwritten.
- `docs/marathons.json` is both the output artifact and the input baseline for the next run.

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

Generate a readable HTML summary and a structured JSON dataset.

Acceptance criteria:

- `docs/index.html` loads in a browser.
- `docs/marathons.json` validates as JSON.
- The HTML page shows the current records in a sortable or scannable table.

### 4. Publish through GitHub Pages

Add a workflow that updates the static site in CI.

Acceptance criteria:

- The workflow runs on schedule.
- The workflow can be run manually.
- The generated `docs/` contents are deployed to GitHub Pages.

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

The repo already contains:

- a curated race list in `config/races.json`
- the update pipeline in `marathon_tracker/`
- rendered static output in `docs/`
- a GitHub Pages workflow in `.github/workflows/marathon-tracker.yml`

The next useful work is to expand the update pipeline with:
- auto-discovery of new races (Phase A)
- refresh prioritisation (Phase B)
- source URL verification (Phase C)
- change the workflow schedule from weekly to daily
then continue expanding source coverage and refining extraction rules as real race pages change.

