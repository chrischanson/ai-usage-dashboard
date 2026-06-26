# Marathon Tracker — Implementation Review & Improvements

> Comprehensive code review of the marathon tracker implementation against [plan.md](file:///home/dev/workspace/main/research/marathon_tracker/plan.md). Each issue is categorized by severity and includes specific file locations and actionable fixes.

---

## Executive Summary

The overall architecture is solid — the three-phase pipeline (Load/Discover → Prioritize → Refresh), the modular scraper system, the SQLite backend with normalized schema, and confidence-gated publishing all follow the plan well. Tests pass (85/85, 1 skipped).

However, the review uncovered **critical data quality problems** in the live database, **significant token waste** in the LLM pipeline, **architectural inefficiencies** in the database layer, and several correctness bugs. These are prioritized below.

---

## Tracking Table

| # | Priority | Summary | Effort | Status | Verified |
|---|----------|---------|--------|--------|----------|
| 1 | P0 🔴 | Fix hallucinated date validation | Medium | ✅ done | ✅ |
| 2 | P0 🔴 | Validate LLM-resolved URLs | Small | ☐ todo | ☐ |
| 3 | P0 🔴 | Stop re-saving carried-over events to `change_log` | Small | ☐ todo | ☐ |
| 4 | P1 🟠 | Single DB connection per run | Medium | ☐ todo | ☐ |
| 5 | P1 🟠 | Reduce page text truncation to 8K chars | Small | ☐ todo | ☐ |
| 6 | P1 🟠 | Reduce LLM URL resolution calls | Medium | ☐ todo | ☐ |
| 7 | P1 🟠 | Remove redundant HEAD check | Small | ☐ todo | ☐ |
| 8 | P1 🟠 | Add page-fetch cache | Small | ☐ todo | ☐ |
| 9 | P2 🟡 | Deduplicate `llm.py` boilerplate | Medium | ☐ todo | ☐ |
| 10 | P2 🟡 | Clean up `db.py` migration spaghetti | Large | ☐ todo | ☐ |
| 11 | P2 🟡 | Share country-to-region mapping | Small | ☐ todo | ☐ |
| 12 | P2 🟡 | Fix silent exception swallowing | Small | ☐ todo | ☐ |
| 13 | P2 🟡 | Move `urlparse` import to module level | Trivial | ☐ todo | ☐ |
| 14 | P3 🟢 | Fix over-eager refresh trigger | Small | ☐ todo | ☐ |
| 15 | P3 🟢 | Document `Race` frozen pattern | Trivial | ☐ todo | ☐ |
| 16 | P3 🟢 | Fix HTML windows-cell markdown-in-HTML | Small | ☐ todo | ☐ |
| 17 | P3 🟢 | Fix `run_update.sh` module path | Trivial | ☐ todo | ☐ |
| 18 | P3 🟢 | Wikipedia O(1) reverse country lookup | Trivial | ☐ todo | ☐ |
| 19 | P3 🟢 | Remove no-op London scraper | Trivial | ☐ todo | ☐ |
| 20 | P3 🟢 | Make `normalize_date()` deterministic | Small | ☐ todo | ☐ |
| 21 | P3 🟢 | Add `change_log` index | Trivial | ☐ todo | ☐ |
| 22 | P3 🟢 | Limit WA discovery to current year | Trivial | ☐ todo | ☐ |

> **Status values:** `☐ todo` · `⚙ in-progress` · `✅ done`  
> **Verified:** check the box once the corresponding **Verifier** passes.

---

## 🔴 Critical — Data Quality Bugs (Fix Immediately)

### 1. Hallucinated "Mock" Dates Accepted as High-Confidence

**Files:** [update.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py), [extract.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/extract.py)

**Problem:** 86 out of 165 events (52%) in the live database have `event_date = '2027-04-19'` and `registration_windows = [2026-09-14 to 2026-09-18]`. The `change_log` notes say `"Successfully extracted mock registration dates."` — these are LLM hallucinations that the pipeline accepted as `confidence = "high"`.

Affected races include Bratislava Marathon, Buriram Marathon, Doha Marathon, Rotterdam Marathon, Guangzhou Marathon, Houston Marathon, etc. — races that absolutely do not share the same date.

**Root Cause:** The `extract_dates()` function in [extract.py L38-63](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/extract.py#L38-L63) blindly trusts whatever the LLM returns without any sanity checks. The `apply_extraction()` function copies over confidence directly from the LLM output. When the LLM hallucinates dates, they are accepted at face value.

**Fix:**
- Add a **date plausibility validator** in `apply_extraction()` that rejects:
  - Event dates that are identical across >3 races in the same batch (statistical anomaly detection).
  - Notes containing words like "mock", "sample", "example", "placeholder".
  - Registration windows that are unrealistically short (e.g., 4 days for a major marathon).
  - Event dates that contradict the historical pattern for that race (e.g., Boston always April, Tokyo always March).
- **Downgrade confidence** to `"low"` if the LLM notes contain suspicious language.
- Add a **post-processing validation step** in `main()` (after Phase C) that flags duplicate dates appearing across multiple unrelated races.

**Verifier:**
```python
# tests/test_extract.py — add these test cases
import unittest
from marathon_tracker.extract import apply_extraction
from marathon_tracker.models import Race, RaceResult

class TestHallucinationGuard(unittest.TestCase):

    def _result(self):
        race = Race(id='test', name='Test Marathon', city='X', country='Y',
                    region='Z', official_url='https://x.com')
        return RaceResult.from_race(race)

    def test_mock_note_downgrades_confidence(self):
        result = self._result()
        apply_extraction(result, {
            'event_date': '2027-04-19',
            'confidence': 'high',
            'notes': 'Successfully extracted mock registration dates.',
            'raw_evidence': [],
            'registration_windows': [],
        }, replace_existing=True)
        self.assertEqual(result.confidence, 'low')  # MUST be downgraded
        self.assertIsNone(result.event_date)         # MUST be rejected

    def test_duplicate_date_across_batch_flagged(self):
        # Simulate post-processing: 5 unrelated races all sharing '2027-04-19'
        from marathon_tracker.update import _flag_duplicate_event_dates
        dates = ['2027-04-19'] * 5
        self.assertTrue(_flag_duplicate_event_dates(dates, threshold=3))

    def test_unrealistically_short_window_rejected(self):
        result = self._result()
        apply_extraction(result, {
            'confidence': 'high',
            'notes': '',
            'raw_evidence': [],
            'registration_windows': [{
                'window_type': 'standard',
                'open_date': '2026-09-14',
                'close_date': '2026-09-18',  # only 4 days
            }],
        }, replace_existing=True)
        self.assertEqual(len(result.registration_windows), 0)  # MUST be rejected
```
All three test cases must pass with `exit 0`. Additionally, run:
```bash
python3 -c "
import sqlite3
c = sqlite3.connect('research/marathon_tracker/docs/marathons.db').cursor()
c.execute(\"SELECT COUNT(*) FROM race_events WHERE event_date='2027-04-19'\")
assert c.fetchone()[0] == 0, 'Bogus dates still present'
print('PASS: no bogus 2027-04-19 dates')
"
```

### 2. No Validation on LLM-Resolved URLs

**Files:** [llm.py L156-241](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/llm.py#L156-L241), [update.py L138-161](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py#L138-L161)

**Problem:** `resolve_official_url()` and `resolve_event_webpage()` accept whatever URL the LLM returns without verifying:
- The URL actually exists (no HTTP HEAD check).
- The URL belongs to the expected domain (an LLM could return a random marathon's URL for the wrong race).
- The URL isn't a generic placeholder (e.g., `https://www.example.com`).

**Fix:**
- After resolving a URL, call `check_url()` to verify it returns 200.
- Optionally fetch the page title/text and check it mentions the race name (fuzzy match).
- Reject URLs with domains like `example.com`, `placeholder`, etc.

**Verifier:**
```python
# tests/test_llm.py — add these test cases
class TestUrlResolutionValidation(unittest.TestCase):

    def test_example_com_rejected(self):
        from marathon_tracker.llm import _validate_resolved_url
        self.assertIsNone(_validate_resolved_url('https://www.example.com'))

    def test_unreachable_url_rejected(self):
        # Monkeypatch check_url to return (False, 'HTTP 404')
        from unittest.mock import patch
        from marathon_tracker.llm import _validate_resolved_url
        with patch('marathon_tracker.llm.check_url', return_value=(False, 'HTTP 404')):
            self.assertIsNone(_validate_resolved_url('https://bogus-marathon-xyz.com'))

    def test_valid_url_passes(self):
        from unittest.mock import patch
        from marathon_tracker.llm import _validate_resolved_url
        with patch('marathon_tracker.llm.check_url', return_value=(True, None)):
            result = _validate_resolved_url('https://www.tcslondonmarathon.com/')
            self.assertIsNotNone(result)
```
All three cases must pass. Additionally confirm the function exists:
```bash
python3 -c "from marathon_tracker.llm import _validate_resolved_url; print('PASS')"
```

### 3. Carried-Over Events Are Re-Saved With New `change_log` Entries Every Run

**Files:** [update.py L388](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py#L388), [config.py L384-401](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/config.py#L384-L401)

**Problem:** `save_race_results(results)` on line 388 of `update.py` saves **all** results, including carried-over ones. Each save creates a new `change_log` entry in [config.py L385-401](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/config.py#L384-L401). This means every daily run appends ~165 new rows to `change_log`, even for events that haven't changed. The DB currently has **3,735 change_log entries** for only 165 events (averaging 22.6 entries per event), and `change_log` details consume **728KB** — 49.5% of the 1.47MB database.

**Fix:**
- In `save_race_results()`, only write a `change_log` entry when the data has actually changed — compare the incoming result with the latest existing `change_log` entry for that event.
- Alternatively, skip `save_race_results()` for results where `extraction_method == "carried-over"`.
- Add a `--prune-log` CLI option or periodic cleanup that keeps only the latest N entries per event.

**Verifier:**
```bash
# Step 1: Run a full update (no-network to avoid real fetches)
python3 -m marathon_tracker.update --no-network --db /tmp/test_verify3.db --docs-dir /tmp/docs3/

# Step 2: Run again (simulating a second daily run)
python3 -m marathon_tracker.update --no-network --db /tmp/test_verify3.db --docs-dir /tmp/docs3/

# Step 3: Assert change_log has AT MOST 1 EXTRACT entry per event after 2 runs
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/test_verify3.db').cursor()
c.execute('''
    SELECT record_id, COUNT(*) as cnt
    FROM change_log
    WHERE table_name='race_events' AND action='EXTRACT'
    GROUP BY record_id
    HAVING cnt > 1
''')
dupes = c.fetchall()
assert len(dupes) == 0, f'FAIL: {len(dupes)} events have multiple EXTRACT entries: {dupes}'
print('PASS: each event has at most 1 change_log EXTRACT entry after 2 runs')
"
```
Expected output: `PASS: each event has at most 1 change_log EXTRACT entry after 2 runs`

---

## 🟠 High — Token Efficiency Issues

### 4. `init_db()` Is Called 4 Times Per Run (Redundant Migrations)

**Files:** [config.py L17-19](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/config.py#L17-L19), [db.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/db.py#L14-L1044)

**Problem:** Every database function (`load_races()`, `load_previous_output()`, `save_races()`, `save_race_results()`) opens a fresh connection, calls `init_db()`, and then closes it. `init_db()` is **1,044 lines** of migration logic that runs every time, performing dozens of `PRAGMA table_info()` checks and conditional DDL operations. In a single update run:
1. `load_previous_output()` -> `init_db()` + close
2. `load_races()` -> `init_db()` + close
3. `save_races()` -> `init_db()` + close (for new discoveries)
4. `save_race_results()` -> `init_db()` + close

This is wasteful. `init_db()` is idempotent but performs ~50 SQL queries per call.

**Fix:**
- Pass a single `sqlite3.Connection` through the pipeline instead of opening/closing per function call.
- Call `init_db()` exactly once at the start of `main()`.
- Pass `conn` as a parameter to `load_races(conn)`, `save_race_results(results, conn)`, etc.
- Close the connection once at the end of `main()`.

**Verifier:**
```bash
# Patch sqlite3.connect to count calls, then run update --no-network
python3 -c "
import sqlite3, unittest.mock as m
call_count = 0
orig = sqlite3.connect
def counting_connect(path, **kw):
    global call_count; call_count += 1; return orig(path, **kw)
with m.patch('sqlite3.connect', side_effect=counting_connect):
    from marathon_tracker import update
    update.main(['--no-network', '--db', '/tmp/verify4.db', '--docs-dir', '/tmp/docs4/'])
print(f'sqlite3.connect called {call_count} time(s)')
assert call_count == 1, f'FAIL: expected 1 call, got {call_count}'
print('PASS')
"
```
Expected output: `sqlite3.connect called 1 time(s)` followed by `PASS`.

### 5. Page Text Truncated to 18,000 Chars — Too Large for Most Pages

**Files:** [llm.py L63](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/llm.py#L63), [llm.py L102](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/llm.py#L102)

**Problem:** The LLM prompt sends up to `page_text[:18000]` characters (~4,500 tokens). Most race pages have the relevant date information in the first 3,000-5,000 characters. The remainder is navigation, footer, legal text, social media links — all irrelevant noise that wastes tokens and increases the chance of hallucination.

**Fix:**
- Reduce the truncation limit to 8,000 characters (~2,000 tokens). This halves token usage per call.
- Before truncation, strip obvious non-content sections: navigation menus, footers, cookie banners, social media embeds. The `html_to_text()` function in [fetch.py L39-42](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/fetch.py#L39-L42) already strips `<script>`, `<style>`, `<noscript>` but doesn't strip `<nav>`, `<footer>`, `<aside>`.
- Consider extracting only the "main content" area using heuristics (look for `<main>`, `<article>`, or the largest `<div>` with date-like text).

**Verifier:**
```bash
# Confirm both truncation constants are <= 8000 in llm.py
python3 -c "
import ast, pathlib
src = pathlib.Path('research/marathon_tracker/marathon_tracker/llm.py').read_text()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.Subscript):
        # Look for Constant slices on 'page_text' or 'content'
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
            limit = node.slice.value
            assert limit <= 8000, f'FAIL: truncation limit {limit} > 8000 at line {node.lineno}'
print('PASS: all truncation limits <= 8000')
"
# Also confirm <nav>/<footer>/<aside> are stripped by html_to_text
python3 -c "
from marathon_tracker.fetch import html_to_text
html = '<html><nav>menu</nav><main>Event Date: April 20 2027</main><footer>copyright</footer></html>'
text = html_to_text(html)
assert 'menu' not in text, 'FAIL: <nav> content leaked into output'
assert 'copyright' not in text, 'FAIL: <footer> content leaked into output'
assert 'April 20 2027' in text, 'FAIL: main content was stripped'
print('PASS: nav/footer stripped, main content preserved')
"
```

### 6. LLM URL Resolution Sends 3 Separate Prompts (Homepage, Webpage, Extraction)

**Files:** [update.py L138-161](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py#L138-L161), [update.py L301-319](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py#L301-L319)

**Problem:** For a race with no URL, the pipeline makes up to **3 LLM calls**:
1. `resolve_official_url(race_name)` in Phase A (line 145).
2. `resolve_event_webpage(race_name, year)` in Phase C (line 311).
3. `extract_with_llm(race_name, page_text)` in Phase C (line 52 of extract.py).

Each call has overhead (API latency, token cost). The first two calls are pure LLM-as-knowledge-source (no page text input), which the plan explicitly warns against: *"Use the LLM only as a parser, not as a source of facts."*

**Fix:**
- Combine the URL resolution into the extraction prompt. When fetching fails, include a note in the extraction prompt: "Additionally, if you know the official URL for this race, include it in the `official_url` field."
- Better yet, **remove the URL resolution LLM calls entirely**. Races without URLs should be discovered with URLs from World Athletics or Wikipedia. If a race has no URL, mark it `confidence = "low"` and skip it until a human provides the URL.
- If URL resolution must stay, batch multiple races into a single LLM call: "Provide the official homepage URLs for the following races: [list]".

**Verifier:**
```bash
# Run --no-network (which disables LLM calls) and count calls to resolve_official_url
python3 -c "
from unittest import mock
call_log = []
with mock.patch('marathon_tracker.llm.resolve_official_url', side_effect=lambda n: call_log.append(n) or '') as m:
    from marathon_tracker import update
    update.main(['--no-network', '--db', '/tmp/verify6.db', '--docs-dir', '/tmp/docs6/'])
print(f'resolve_official_url called {len(call_log)} times during --no-network run')
assert len(call_log) == 0, f'FAIL: should not call LLM URL resolution at all'
print('PASS: no LLM URL resolution calls in --no-network mode')
"
# For network-enabled runs, verify at most 1 LLM call per race (not 2-3):
# grep for calls to both resolve_official_url and resolve_event_webpage in update.py
python3 -c "
import pathlib, re
src = pathlib.Path('research/marathon_tracker/marathon_tracker/update.py').read_text()
calls = re.findall(r'resolve_official_url|resolve_event_webpage', src)
print(f'LLM URL resolution call sites in update.py: {calls}')
assert len(calls) == 0, f'FAIL: update.py still calls LLM URL resolution {len(calls)} time(s)'
print('PASS: no LLM URL resolution call sites in update.py')
"
```
Expected: both assertions pass.

### 7. Redundant `check_url()` HEAD Request Before `fetch_text()` GET

**Files:** [update.py L328-342](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py#L328-L342)

**Problem:** The pipeline sends an HTTP HEAD request (`check_url()`) and then immediately sends a GET request (`fetch_text()`) to the same URL. The HEAD request is redundant — if the page is down, the GET will fail too, and `fetch_text()` already has retry logic.

**Fix:**
- Remove the `check_url()` call. Let `fetch_text()` handle errors directly.
- If `fetch_text()` raises a `RuntimeError`, set `status = "stale"` and `confidence = "low"` (same as the current HEAD-failure path).
- This eliminates one HTTP request per race, saving ~100+ network calls per run.

**Verifier:**
```bash
# Confirm check_url is no longer called from update.py's Phase C loop
python3 -c "
import pathlib, ast
src = pathlib.Path('research/marathon_tracker/marathon_tracker/update.py').read_text()
tree = ast.parse(src)
calls = [n for n in ast.walk(tree)
         if isinstance(n, ast.Call)
         and isinstance(getattr(n.func, 'id', None), str)
         and n.func.id == 'check_url']
print(f'check_url call sites in update.py: {len(calls)}')
assert len(calls) == 0, f'FAIL: check_url still called {len(calls)} times in update.py'
print('PASS: check_url not called from update.py')
"
# Confirm fetch.py handles errors and raises RuntimeError on 4xx/5xx
python3 -c "
from unittest import mock
import urllib.error
from marathon_tracker.fetch import fetch_text
with mock.patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError(None, 404, 'Not Found', {}, None)):
    try:
        fetch_text('https://fake.example.com')
        print('FAIL: RuntimeError not raised')
    except RuntimeError:
        print('PASS: RuntimeError raised on 4xx')
"
```

### 8. No Caching of Fetched Pages Between Runs

**Files:** [fetch.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/fetch.py)

**Problem:** If a run is interrupted (e.g., LLM 429 quota error), the next run re-fetches all the same pages. There's no local cache of fetched HTML.

**Fix:**
- Add a simple file-based cache in `docs/.cache/` keyed by URL hash. Store fetched HTML with a timestamp.
- On fetch, check cache first. If the cached version is <24 hours old, use it.
- This prevents redundant fetches when reruns happen due to quota limits or crashes.

**Verifier:**
```bash
# Confirm fetch_text uses cache on second call to same URL
python3 -c "
import pathlib, tempfile, os
from unittest import mock
from marathon_tracker.fetch import fetch_text

fetch_call_count = 0
orig_urlopen = __import__('urllib.request', fromlist=['urlopen']).urlopen
def counting_urlopen(req, **kw):
    global fetch_call_count; fetch_call_count += 1
    return orig_urlopen(req, **kw)

with tempfile.TemporaryDirectory() as cache_dir:
    os.environ['FETCH_CACHE_DIR'] = cache_dir
    with mock.patch('urllib.request.urlopen', side_effect=counting_urlopen):
        # First call — must hit network
        try: fetch_text('https://httpbin.org/html')
        except Exception: pass
        first_count = fetch_call_count
        # Second call — must use cache
        try: fetch_text('https://httpbin.org/html')
        except Exception: pass
        second_count = fetch_call_count
    assert second_count == first_count, f'FAIL: urlopen called {second_count - first_count} extra time(s) on cache hit'
    print('PASS: second fetch used cache, no extra urlopen call')
"
```

---

## 🟡 Medium — Code Quality & Architecture

### 9. Massive Code Duplication in `llm.py`

**File:** [llm.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/llm.py)

**Problem:** `extract_with_llm()`, `resolve_official_url()`, and `resolve_event_webpage()` each duplicate the same API/agy/opencode fallback chain. The file is 336 lines, but ~250 of those are copy-pasted boilerplate:
- Build API request -> try API -> fallback to agy -> fallback to opencode.
- The `re` and `shutil` imports are inside function bodies (repeated 3 times each).

**Fix:**
- Extract a shared `_call_llm(prompt: str, parse_fn: Callable) -> str | None` helper that encapsulates the API/CLI fallback chain.
- `extract_with_llm()`, `resolve_official_url()`, and `resolve_event_webpage()` become thin wrappers that construct a prompt and call `_call_llm()`.
- Move imports to module level.
- This reduces `llm.py` from ~336 lines to ~120 lines.

**Verifier:**
```bash
# 1. Confirm llm.py line count has been reduced
python3 -c "
import pathlib
lines = len(pathlib.Path('research/marathon_tracker/marathon_tracker/llm.py').read_text().splitlines())
print(f'llm.py line count: {lines}')
assert lines <= 180, f'FAIL: expected <= 180 lines after refactor, got {lines}'
print('PASS')
"
# 2. Confirm the shared helper exists
python3 -c "from marathon_tracker.llm import _call_llm; print('PASS: _call_llm exists')"
# 3. Confirm existing tests still pass (no regressions)
PYTHONPATH=research/marathon_tracker python3 -m unittest research.marathon_tracker.tests.test_llm -v 2>&1 | tail -3
```
Expected: line count ≤ 180, `_call_llm` importable, all test_llm tests pass.

### 10. `db.py` Migration Code Is 1,044 Lines of Spaghetti

**File:** [db.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/db.py)

**Problem:** `init_db()` is a single function that handles 6+ migration steps across multiple schema versions. It contains:
- Duplicated `CREATE TABLE` statements (the same table DDL appears 3-4 times in different migration branches).
- Migrations that will never run again (e.g., `locations` -> `loc_locations`, `races` -> `race_races`).
- A disabled trigger block (`if False:` on line 926).
- No schema version tracking — it uses `PRAGMA table_info()` heuristics to detect the current state.

**Fix:**
- Add a `schema_version` table with a single integer. Each migration checks the version and runs only if needed.
- Move completed migrations to a separate `migrations/` directory or remove them entirely (the DB has already been migrated).
- Keep only the "create fresh" DDL in `init_db()` for new databases.
- Remove the dead `if False:` trigger block or re-enable it.
- This would reduce `db.py` from 1,140 lines to ~200 lines.

**Verifier:**
```bash
# 1. Line count
python3 -c "
import pathlib
lines = len(pathlib.Path('research/marathon_tracker/marathon_tracker/db.py').read_text().splitlines())
print(f'db.py line count: {lines}')
assert lines <= 400, f'FAIL: expected <= 400 lines after refactor, got {lines}'
print('PASS: line count ok')
"
# 2. schema_version table exists and is seeded correctly on fresh DB
python3 -c "
import sqlite3, tempfile
from marathon_tracker.db import get_connection, init_db
with tempfile.NamedTemporaryFile(suffix='.db') as f:
    conn = get_connection(f.name)
    init_db(conn)
    c = conn.cursor()
    c.execute(\"SELECT version FROM schema_version\")
    v = c.fetchone()[0]
    assert isinstance(v, int) and v >= 1, f'FAIL: bad schema_version {v}'
    print(f'PASS: schema_version = {v}')
"
# 3. No dead 'if False:' blocks remain
python3 -c "
import pathlib
src = pathlib.Path('research/marathon_tracker/marathon_tracker/db.py').read_text()
assert 'if False:' not in src, 'FAIL: dead if False: block still present'
print('PASS: no dead if False: block')
"
# 4. Existing trigger tests pass
PYTHONPATH=research/marathon_tracker python3 -m unittest research.marathon_tracker.tests.test_triggers -v 2>&1 | tail -3
```

### 11. `_guess_region()` in `discover.py` Duplicates `_seed_loc_regions_and_countries()` in `db.py`

**Files:** [discover.py L404-453](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/discover.py#L404-L453), [db.py L1047-1093](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/db.py#L1047-L1093)

**Problem:** Both files maintain independent hardcoded country-to-region mappings. If a country is added to one but not the other, they'll disagree.

**Fix:**
- Extract the country-to-region mapping to a single shared data source (e.g., a JSON file or a module-level dict in a `constants.py` module).
- Both `discover.py` and `db.py` import from this shared source.

**Verifier:**
```bash
# 1. Confirm constants module (or equivalent) exists and is imported by both files
python3 -c "from marathon_tracker.constants import COUNTRY_REGION_MAP; print(f'PASS: {len(COUNTRY_REGION_MAP)} countries')"
# 2. The two sets must be identical
python3 -c "
from marathon_tracker.constants import COUNTRY_REGION_MAP
from marathon_tracker.db import _seed_loc_regions_and_countries
import sqlite3, tempfile
with tempfile.NamedTemporaryFile(suffix='.db') as f:
    conn = sqlite3.connect(f.name)
    conn.execute('CREATE TABLE loc_regions (name TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE loc_countries (name TEXT PRIMARY KEY, region_name TEXT NOT NULL)')
    _seed_loc_regions_and_countries(conn)
    db_countries = set(r[0] for r in conn.execute('SELECT name FROM loc_countries').fetchall())
const_countries = set(COUNTRY_REGION_MAP.keys())
diff = db_countries.symmetric_difference(const_countries)
assert not diff, f'FAIL: mismatch between db and constants: {diff}'
print('PASS: db and constants country sets are identical')
"
# 3. discover.py no longer contains a hardcoded country set literal
python3 -c "
import pathlib, ast
src = pathlib.Path('research/marathon_tracker/marathon_tracker/discover.py').read_text()
tree = ast.parse(src)
north_am_literal = any(
    isinstance(n, ast.Set) and len(n.elts) > 5
    for n in ast.walk(tree)
)
assert not north_am_literal, 'FAIL: hardcoded country set literal still in discover.py'
print('PASS: no hardcoded country set in discover.py')
"
```

### 12. Silent `except Exception: pass` Swallows Real Errors

**Files:** [config.py L235-236](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/config.py#L235-L236), [llm.py L198](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/llm.py#L198), [llm.py L219](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/llm.py#L219)

**Problem:** Multiple places use bare `except Exception: pass` which swallows constraint violations, type errors, and other bugs silently. In `save_races()` line 235, if an `IntegrityError` occurs, the race is silently skipped with no logging.

**Fix:**
- Log the exception (at minimum, print to stderr with the race name).
- Use specific exception types (`sqlite3.IntegrityError`) instead of bare `Exception`.

**Verifier:**
```bash
# 1. No bare 'except Exception: pass' or 'except: pass' remains in any source file
python3 -c "
import pathlib, ast
fails = []
for p in pathlib.Path('research/marathon_tracker/marathon_tracker').rglob('*.py'):
    src = p.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            is_pass_only = len(body) == 1 and isinstance(body[0], ast.Pass)
            catches_all = node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == 'Exception'
            )
            if is_pass_only and catches_all:
                fails.append(f'{p.name}:L{node.lineno}')
assert not fails, f'FAIL: bare except/pass at {fails}'
print('PASS: no bare except-pass found')
"
# 2. Verify a real IntegrityError in save_races is logged, not silently swallowed
python3 -c "
import sqlite3, tempfile, io, sys
from marathon_tracker.models import Race
from marathon_tracker.config import save_races
from marathon_tracker.db import get_connection, init_db
# Insert race once, then try inserting a duplicate — should print a warning, not crash
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path = f.name
race = Race(id='r1', name='Test', city='X', country='United States', region='North America', official_url='https://x.com')
save_races([race], db_path)
captured = io.StringIO()
sys.stderr = captured
save_races([race], db_path)  # duplicate — should log, not crash
sys.stderr = sys.__stderr__
print('stderr output:', repr(captured.getvalue()))
assert captured.getvalue() != '', 'FAIL: no warning logged on duplicate insert'
print('PASS: duplicate insert produced a logged warning')
"
```

### 13. `save_race_results()` Imports `urlparse` Inside Loop

**File:** [config.py L257](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/config.py#L257)

**Problem:** `from urllib.parse import urlparse` is imported inside the `for result in results:` loop. This is a minor perf issue (import is cached after first call) but is bad practice.

**Fix:** Move the import to module level.

**Verifier:**
```bash
# Confirm 'from urllib.parse import urlparse' does NOT appear inside a function body in config.py
python3 -c "
import ast, pathlib
src = pathlib.Path('research/marathon_tracker/marathon_tracker/config.py').read_text()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for child in ast.walk(node):
            if isinstance(child, ast.ImportFrom):
                if child.module and 'urllib' in child.module:
                    raise AssertionError(f'FAIL: urllib import inside function at L{child.lineno}')
print('PASS: urlparse imported at module level')
"
```

---

## 🟢 Low — Enhancements & Polish

### 14. `_needs_refresh()` Triggers Refresh for ALL Races With No Registration Windows

**File:** [update.py L86-87](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/update.py#L86-L87)

**Problem:** The condition `len(result.registration_windows) == 0` triggers a refresh for any race with no registration windows, even if the race was just refreshed and the official page genuinely doesn't list registration windows. This causes the same races to be refreshed every run.

**Fix:**
- Only trigger the "no registration windows" refresh if `extracted_at` is older than 7 days, or if `extraction_method` is `"seed"`.
- Add a `--force-refresh` flag for cases where a human wants to override the skip logic.

**Verifier:**
```python
# tests/test_update.py — add this test
class TestRefreshTrigger(unittest.TestCase):

    def _result_with_empty_windows_recently_extracted(self):
        from marathon_tracker.models import Race, RaceResult
        from datetime import datetime, timezone, timedelta
        race = Race(id='r', name='R', city='C', country='US', region='NA', official_url='https://x.com')
        r = RaceResult.from_race(race)
        r.registration_windows = []  # empty windows
        r.extraction_method = 'llm'  # was actually extracted
        # extracted 2 hours ago (well within 7-day window)
        r.extracted_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return r

    def test_no_windows_but_recently_extracted_does_not_refresh(self):
        from marathon_tracker.update import _needs_refresh
        result = self._result_with_empty_windows_recently_extracted()
        # Must NOT trigger refresh — the page was just checked
        self.assertFalse(_needs_refresh(result))

    def test_no_windows_and_seed_method_triggers_refresh(self):
        from marathon_tracker.update import _needs_refresh
        result = self._result_with_empty_windows_recently_extracted()
        result.extraction_method = 'seed'  # never truly extracted
        self.assertTrue(_needs_refresh(result))
```
Run with:
```bash
PYTHONPATH=research/marathon_tracker python3 -m unittest research.marathon_tracker.tests.test_update.TestRefreshTrigger -v
```
Both tests must pass.

### 15. The `Race` Dataclass Has `registration_windows` but Is `frozen=True`

**File:** [models.py L36-48](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/models.py#L36-L48)

**Problem:** `Race` is `frozen=True` but uses `list[RegistrationWindow]` as a default field. This is fine for immutability but awkward when constructing — you must pass windows at construction time. The `update.py` code uses `dataclasses.replace()` to modify `Race` objects, which is correct but verbose.

**Fix:** This is a minor design concern, not a bug. Consider making `Race` non-frozen if `replace()` is used frequently, or documenting the pattern.

**Verifier:**
```bash
# Confirm a docstring or comment explaining the frozen+replace pattern exists in models.py or update.py
python3 -c "
import pathlib
for f in ['research/marathon_tracker/marathon_tracker/models.py',
          'research/marathon_tracker/marathon_tracker/update.py']:
    src = pathlib.Path(f).read_text()
    if 'dataclasses.replace' in src and ('frozen' in src or 'immutable' in src):
        print(f'PASS: pattern documented in {f}')
        exit(0)
print('WARN: no documentation found — add a comment explaining frozen+replace pattern')
"
```

### 16. HTML Output Has XSS Potential in Notes Field

**File:** [render.py L238](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/render.py#L238)

**Problem:** The `notes_html` line uses `esc_html()` correctly, but the `windows_cell` uses `**bold**` markdown syntax inside HTML (`render_row`), then regex-replaces it into `<strong>` tags. This mixing of markdown and HTML is fragile.

**Fix:**
- Use `html.escape()` consistently for all user-facing content in the HTML renderer.
- Build HTML directly instead of converting markdown-in-HTML.

**Verifier:**
```bash
# 1. No '**' markdown bold markers should appear in render_row output
python3 -c "
from marathon_tracker.render import render_row
from marathon_tracker.models import RaceResult
from marathon_tracker.models import Race
race = Race(id='t', name='Test Marathon', city='London', country='United Kingdom', region='Europe', official_url='https://x.com')
r = RaceResult.from_race(race)
from marathon_tracker.models import RegistrationWindow
r.registration_windows = [RegistrationWindow(window_type='standard', open_date='2026-01-01', close_date='2026-06-01', description='Standard Entry')]
html = render_row(r.to_dict())
assert '**' not in html, f'FAIL: markdown bold markers in HTML output: {html[:200]}'
print('PASS: no markdown bold in HTML output')
"
# 2. Confirm <strong> tags are present instead
python3 -c "
from marathon_tracker.render import render_row
from marathon_tracker.models import Race, RaceResult, RegistrationWindow
race = Race(id='t', name='T', city='C', country='United Kingdom', region='Europe', official_url='https://x.com')
r = RaceResult.from_race(race)
r.registration_windows = [RegistrationWindow(window_type='lottery', open_date=None, close_date='2026-09-01', description='Lottery')]
html = render_row(r.to_dict())
assert '<strong>' in html, 'FAIL: <strong> tag missing in HTML output'
print('PASS: <strong> tag present')
"
```

### 17. `run_update.sh` Uses `cd` to Repo Root

**File:** [run_update.sh L18](file:///home/dev/workspace/main/research/marathon_tracker/run_update.sh#L18)

**Problem:** The script `cd`s to `$REPO_ROOT` and runs the module with a deeply nested path: `python3 -m research.marathon_tracker.marathon_tracker.update`. This is fragile and couples the script to the repo layout.

**Fix:**
- Use `PYTHONPATH` instead: `PYTHONPATH="$SCRIPT_DIR" python3 -m marathon_tracker.update "$@"`
- This matches the pattern used in the test command documented in plan.md.

**Verifier:**
```bash
# Confirm the script uses PYTHONPATH instead of cd + deeply nested module path
python3 -c "
import pathlib
src = pathlib.Path('research/marathon_tracker/run_update.sh').read_text()
assert 'PYTHONPATH' in src, 'FAIL: PYTHONPATH not used in run_update.sh'
assert 'research.marathon_tracker.marathon_tracker.update' not in src, \
    'FAIL: old deeply nested module path still present'
assert 'marathon_tracker.update' in src, 'FAIL: correct module path not found'
print('PASS: run_update.sh uses PYTHONPATH correctly')
"
# Functional test: the script actually runs
bash research/marathon_tracker/run_update.sh --no-network --help 2>&1 | grep -q 'usage:' && echo 'PASS: --help works' || echo 'FAIL: script does not run'
```

### 18. Wikipedia Discovery Does Reverse Country Lookup Inefficiently

**File:** [discover.py L276-280](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/discover.py#L276-L280)

**Problem:** For each Wikipedia candidate, the code iterates through the entire `country_map` (250+ entries) to find a country code by name. This is O(n) per candidate.

**Fix:**
- Build a reverse lookup dict (`name -> code`) once and use it for all candidates. This is O(1) per candidate after a one-time O(n) build.

**Verifier:**
```bash
# Confirm discover_from_wikipedia_page no longer iterates country_map per row
python3 -c "
import ast, pathlib
src = pathlib.Path('research/marathon_tracker/marathon_tracker/discover.py').read_text()
tree = ast.parse(src)
# Find the discover_from_wikipedia_page function
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'discover_from_wikipedia_page':
        # Look for a for-loop over country_map inside the per-row loop
        inner_for_loops = [n for n in ast.walk(node) if isinstance(n, ast.For)]
        nested = [l for l in inner_for_loops if any(
            isinstance(n, ast.For) for n in ast.walk(l)
            if n is not l
        )]
        assert len(nested) == 0, f'FAIL: nested loops (O(n) lookup) still present in discover_from_wikipedia_page'
print('PASS: no nested loops in discover_from_wikipedia_page')
"
# Functional check: discovery runs without regression
PYTHONPATH=research/marathon_tracker python3 -m unittest research.marathon_tracker.tests.test_discover -v 2>&1 | tail -4
```

### 19. London Marathon Custom Scraper Does Nothing Custom

**File:** [london_marathon.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/scrapers/london_marathon.py)

**Problem:** The custom scraper for `london-marathon` just calls `fetch_text()` then `extract_dates()`, which is identical to the generic path. The only difference is it doesn't run `check_url()` first (which is actually a regression — no URL validation).

**Fix:**
- Either remove the custom scraper (let it fall through to generic) or add actual London-specific parsing logic (e.g., parsing the TCS London Marathon ballot page structure).

**Verifier:**
```bash
# Option A — scraper removed: get_scraper('london-marathon') must return None
python3 -c "
from marathon_tracker.scrapers import get_scraper
scraper = get_scraper('london-marathon')
if scraper is None:
    print('PASS (Option A): london-marathon scraper removed, falls through to generic')
else:
    # Option B — scraper kept: must contain non-trivial custom logic beyond fetch+extract_dates
    import inspect
    src = inspect.getsource(scraper)
    assert 'tcslondonmarathon' in src.lower() or 'ballot' in src.lower() or 'ballot_entry' in src.lower(), \
        'FAIL (Option B): london scraper still just calls generic extract_dates with no custom logic'
    print('PASS (Option B): london scraper has custom parsing logic')
"
```

### 20. `normalize_date()` Rejects Dates Older Than `current_year - 1`

**File:** [extract.py L212-213](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/extract.py#L212-L213)

**Problem:** `datetime.now().year` is called inside `normalize_date()`, making it non-deterministic and hard to test. Also, rejecting dates from 2+ years ago means historical data can't be ingested.

**Fix:**
- Pass the current year as a parameter, or use a module-level `_now()` function for testability.
- Consider a softer policy: accept old dates but mark confidence as `"low"`.

**Verifier:**
```python
# tests/test_extract.py — add this test
class TestNormalizeDateDeterminism(unittest.TestCase):

    def test_normalize_date_accepts_year_parameter(self):
        from marathon_tracker.extract import normalize_date
        import inspect
        sig = inspect.signature(normalize_date)
        self.assertIn('current_year', sig.parameters,
                      'normalize_date must accept a current_year parameter')

    def test_normalize_date_is_deterministic(self):
        from marathon_tracker.extract import normalize_date
        # Same input, two different 'current_year' values -> different results
        result_2027 = normalize_date('March 15, 2025', current_year=2027)
        result_2026 = normalize_date('March 15, 2025', current_year=2026)
        # 2025 is current_year-1 for 2026 -> accepted
        self.assertIsNotNone(result_2026)
        # 2025 is current_year-2 for 2027 -> rejected (or returned as low confidence)
        # Either None or '2025-03-15' is acceptable as long as the year param controls it
        # The key test is the function doesn't call datetime.now() internally:
        from unittest.mock import patch
        with patch('marathon_tracker.extract.datetime') as mock_dt:
            mock_dt.now.side_effect = AssertionError('datetime.now() must not be called inside normalize_date')
            mock_dt.strptime = __import__('datetime').datetime.strptime
            normalize_date('March 15, 2026', current_year=2027)  # must not call datetime.now()
```
Run with `PYTHONPATH=research/marathon_tracker python3 -m unittest research.marathon_tracker.tests.test_extract.TestNormalizeDateDeterminism -v`.

### 21. Missing Index on `change_log` for Performance

**File:** [db.py](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/db.py)

**Problem:** `load_previous_output()` in [config.py L95-101](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/config.py#L95-L101) runs a correlated subquery against `change_log` for every event:
```sql
SELECT id FROM change_log
WHERE table_name = 'race_events'
  AND action = 'EXTRACT'
  AND record_id = CAST(e.id AS TEXT)
ORDER BY id DESC LIMIT 1
```
With 3,735 rows (and growing), this is a full table scan per event.

**Fix:**
- Add an index: `CREATE INDEX IF NOT EXISTS idx_changelog_event ON change_log(table_name, action, record_id);`

**Verifier:**
```bash
# Confirm the index exists in the live DB and in init_db() DDL
python3 -c "
import sqlite3
conn = sqlite3.connect('research/marathon_tracker/docs/marathons.db')
c = conn.cursor()
c.execute(\"SELECT name FROM sqlite_master WHERE type='index' AND name='idx_changelog_event'\")
row = c.fetchone()
assert row, 'FAIL: index idx_changelog_event not found in live DB'
print(f'PASS: index {row[0]} exists in DB')
"
# Also confirm the CREATE INDEX statement is in db.py
python3 -c "
import pathlib
src = pathlib.Path('research/marathon_tracker/marathon_tracker/db.py').read_text()
assert 'idx_changelog_event' in src, 'FAIL: idx_changelog_event not defined in db.py'
print('PASS: index definition found in db.py')
"
# Confirm EXPLAIN QUERY PLAN uses the index (not a full scan)
python3 -c "
import sqlite3
conn = sqlite3.connect('research/marathon_tracker/docs/marathons.db')
c = conn.cursor()
c.execute(\"EXPLAIN QUERY PLAN SELECT id FROM change_log WHERE table_name='race_events' AND action='EXTRACT' AND record_id='1' ORDER BY id DESC LIMIT 1\")
plan = c.fetchall()
plan_str = str(plan)
print('Query plan:', plan_str)
assert 'SCAN' not in plan_str or 'USING INDEX' in plan_str or 'USING COVERING INDEX' in plan_str, \
    'FAIL: query plan uses full table SCAN instead of index'
print('PASS: query uses index')
"
```

### 22. `discover.py` Queries Both Current and Previous Year from World Athletics

**File:** [discover.py L178](file:///home/dev/workspace/main/research/marathon_tracker/marathon_tracker/discover.py#L178)

**Problem:** `seasons = [current_year, current_year - 1]` queries two years of data from World Athletics. Past-year races are already in the database and won't need re-discovery. This doubles the API calls unnecessarily.

**Fix:**
- Only query the current year by default. Add a `--discover-backfill` flag for querying previous years during initial setup.

**Verifier:**
```bash
# 1. Default seasons list must contain exactly one entry (current year)
python3 -c "
from unittest import mock
import datetime
calls = []
with mock.patch('marathon_tracker.discover._run_graphql', side_effect=lambda s, g: calls.append(s) or []) as m:
    from marathon_tracker.discover import discover_from_world_athletics
    discover_from_world_athletics()  # default, no backfill
print(f'Seasons queried: {calls}')
assert len(set(calls)) == 1, f'FAIL: expected 1 season, got {set(calls)}'
assert calls[0] == datetime.datetime.now().year, f'FAIL: wrong year {calls[0]}'
print('PASS: only current year queried by default')
"
# 2. --discover-backfill must query current_year AND current_year-1
python3 -c "
from unittest import mock
import datetime
calls = []
with mock.patch('marathon_tracker.discover._run_graphql', side_effect=lambda s, g: calls.append(s) or []):
    from marathon_tracker.discover import discover_from_world_athletics
    discover_from_world_athletics(backfill=True)
print(f'Seasons queried with backfill: {calls}')
assert len(set(calls)) == 2, f'FAIL: expected 2 seasons with backfill, got {set(calls)}'
print('PASS: two seasons queried with backfill=True')
"
# 3. Existing discover tests pass
PYTHONPATH=research/marathon_tracker python3 -m unittest research.marathon_tracker.tests.test_discover -v 2>&1 | tail -4
```

---

## Data Quality Summary

| Metric | Current Value | Expected |
|--------|--------------|----------|
| Races in DB | 105 | — |
| Events in DB | 165 | — |
| Events with bogus `2027-04-19` date | **86 (52%)** | 0 |
| Events with identical registration window | **86** | 0 |
| `change_log` entries | **3,735** | ~165 (1 per event) |
| `change_log` size | **728KB (49.5% of DB)** | <50KB |
| DB file size | 1.47MB | <500KB |
| `init_db()` calls per run | **4** | 1 |
| LLM calls for URL resolution per run | Up to 2 x N races | 0 (ideally) |

---

## Implementation Priority

See the [Tracking Table](#tracking-table) at the top for live status.

| Priority | Issue # | Summary | Effort |
|----------|---------|---------|--------|
| P0 🔴 | 1 | Fix hallucinated date validation | Medium |
| P0 🔴 | 3 | Stop re-saving carried-over events to `change_log` | Small |
| P0 🔴 | 2 | Validate LLM-resolved URLs | Small |
| P1 🟠 | 4 | Single DB connection per run | Medium |
| P1 🟠 | 5 | Reduce page text truncation to 8K chars | Small |
| P1 🟠 | 7 | Remove redundant HEAD check | Small |
| P1 🟠 | 6 | Reduce LLM URL resolution calls | Medium |
| P1 🟠 | 8 | Add page-fetch cache | Small |
| P2 🟡 | 9 | Deduplicate `llm.py` boilerplate | Medium |
| P2 🟡 | 10 | Clean up `db.py` migration spaghetti | Large |
| P2 🟡 | 14 | Fix over-eager refresh trigger | Small |
| P2 🟡 | 11 | Share country-to-region mapping | Small |
| P2 🟡 | 12 | Fix silent exception swallowing | Small |
| P2 🟡 | 13 | Move `urlparse` import to module level | Trivial |
| P2 🟡 | 21 | Add `change_log` index | Trivial |
| P3 🟢 | 15 | Document `Race` frozen pattern | Trivial |
| P3 🟢 | 16 | Fix HTML windows-cell markdown-in-HTML | Small |
| P3 🟢 | 17 | Fix `run_update.sh` module path | Trivial |
| P3 🟢 | 18 | Wikipedia O(1) reverse country lookup | Trivial |
| P3 🟢 | 19 | Remove no-op London scraper | Trivial |
| P3 🟢 | 20 | Make `normalize_date()` deterministic | Small |
| P3 🟢 | 22 | Limit WA discovery to current year | Trivial |

---

## One-Time Data Cleanup Required

Before any code improvements, the live database needs a one-time cleanup:

1. **Reset events with `event_date = '2027-04-19'`** to NULL — these are hallucinated.
2. **Delete registration windows with `open_date = '2026-09-14' AND close_date = '2026-09-18'`** — these are hallucinated.
3. **Prune `change_log`** to keep only the latest entry per event.
4. **VACUUM** the database after cleanup.

```sql
-- Cleanup script (run manually after backing up)
UPDATE race_events SET event_date = NULL WHERE event_date = '2027-04-19';
DELETE FROM race_registration_windows WHERE open_date = '2026-09-14' AND close_date = '2026-09-18';

-- Keep only latest change_log entry per event
DELETE FROM change_log WHERE id NOT IN (
    SELECT MAX(id) FROM change_log
    WHERE table_name = 'race_events' AND action = 'EXTRACT'
    GROUP BY record_id
) AND table_name = 'race_events' AND action = 'EXTRACT';

VACUUM;
```
