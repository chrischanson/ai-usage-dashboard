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

The system follows a simple loop:

1. Load the curated race list from `config/races.json`.
2. Discover new races from external directories or community-maintained lists (e.g. Wikipedia, World Athletics calendar), merge them into the current set.
3. Fetch the official source page for each race.
3. Ask the LLM to extract date fields when credentials are available.
4. Fall back to deterministic regex extraction when the LLM is unavailable.
5. Merge the extracted data into a stable result record.
6. Render `docs/marathons.json` and `docs/index.html`.
7. Publish `docs/` through GitHub Pages.

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
- The GitHub Actions workflow refreshes the data on a schedule and on manual dispatch.
- If the repo has an `LLM_API_KEY` secret, the workflow can extract richer data in CI.

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

### 6. Keep the data fresh

As race sites change, the tracker should continue to update records rather than freezing them.

Acceptance criteria:

- New dates can be added without changing the code.
- Broken source URLs do not stop the entire update run.
- The latest data remains visible on the published page.

## Risks

- Race sites change URLs frequently.
- Some pages block or redirect automated fetches.
- Date text may be ambiguous unless the source page is carefully chosen.
- LLM output is only as good as the page text provided to it.

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

The next useful work is to build the auto-discovery pipeline so new races are picked up without manual curation, then continue expanding source coverage and refining extraction rules as real race pages change.

