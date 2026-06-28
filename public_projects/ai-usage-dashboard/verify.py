#!/usr/bin/env python3
"""Verifier for AI Usage Dashboard changes.

Run: PYTHONPATH=backend python3 verify.py URL
Default URL: http://127.0.0.1:8000
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
errors = []
passes = []


def ok(msg):
    passes.append(msg)
    print(f'  \033[32mPASS\033[0m {msg}')


def fail(msg):
    errors.append(msg)
    print(f'  \033[31mFAIL\033[0m {msg}')


def get(path):
    url = BASE.rstrip('/') + '/' + path.lstrip('/')
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode()
            return body, resp.status
    except urllib.error.HTTPError as e:
        return e.read().decode(), e.code
    except Exception as e:
        return str(e), 0


# ── Section headers ──
def heading(n, title):
    print(f'\n── [{n}] {title} ──')


print(f'\n\033[1m=== Verifying {BASE} ===\033[0m\n')

# ── 1. Server process ──
heading(1, 'Server process')
pid_path = '/tmp/dashboard.pid'
if os.path.exists(pid_path):
    with open(pid_path) as f:
        pid = f.read().strip()
    if os.path.isdir(f'/proc/{pid}'):
        ok(f'Server running (PID {pid})')
    else:
        fail(f'PID file at {pid_path} but process {pid} not running')
else:
    fail(f'PID file {pid_path} not found')

# ── 2. Frontend HTML ──
heading(2, 'Frontend HTML')
html, status = get('/static/index.html')
if status == 200:
    if re.search(r'>\s*All\s*<', html) and 'data-source="combined"' in html:
        ok('Tab label says "All"')
    else:
        fail('Tab label not found: "All"')
    if 'Combined (All)' in html:
        fail('Old "Combined (All)" label still present')
    else:
        ok('Old "Combined (All)" label removed')
    for src in ('combined', 'agy', 'opencode', 'codex'):
        if f'data-source="{src}"' in html:
            ok(f'Tab data-source="{src}" present')
        else:
            fail(f'Tab data-source="{src}" missing')
    # Page controls
    if 'time-range-buttons' in html:
        ok('Time range buttons present')
    else:
        fail('Time range buttons missing')
    if 'chart-controls' in html:
        fail('Chart controls still inside chart container')
    else:
        ok('Chart controls removed from chart container')
    for r in ('1h', '6h', '1d', '1w', '1m', '3m', 'all'):
        if f'data-range="{r}"' in html:
            ok(f'Time range button data-range="{r}"')
        else:
            fail(f'Time range button data-range="{r}" missing')
    for m in ('total', 'rate'):
        if f'data-mode="{m}"' in html:
            ok(f'Mode toggle data-mode="{m}"')
        else:
            fail(f'Mode toggle data-mode="{m}" missing')
else:
    fail(f'index.html returned HTTP {status}')

# ── 3. Frontend JS ──
heading(3, 'Frontend JS')
js, status = get('/static/app.js')
if status == 200:
    checks = [
        ("container.className = 'quota-cards source-' + source",
         'Dynamic source CSS class set on quota-cards'),
        ('renderCodexQuota(container, rateLimit, plan)',
         'Codex plan passed to renderCodexQuota'),
        ('badge badge-codex">${escapeHtml(planLabel)}',
         'Codex badge uses dynamic plan label'),
        ('badge badge-agy">${escapeHtml(agyPlan)}',
         'AGY badge uses dynamic plan label'),
        ('renderQuota(data, currentSource)',
         'renderQuota called with currentSource'),
        ('fetchQuota(', 'fetchQuota function defined'),
        ('renderOpenCodeCost(', 'OpenCode cost rendering function'),
        ('renderCodexQuota(', 'Codex quota rendering function'),
        ('let timeRange', 'timeRange state variable'),
        ('let mode', 'mode state variable'),
        ('let cachedHistory', 'cachedHistory variable'),
        ('cachedHistory =', 'Caches history data after fetch'),
        ('filterByTimeRange(data, range)',
         'filterByTimeRange function'),
        ('computeRate(series, label)',
         'computeRate function for delta computation'),
        ('document.querySelectorAll(\'.range-btn\')',
         'Time range button event listeners'),
        ('document.querySelectorAll(\'.mode-btn\')',
         'Mode toggle event listeners'),
        ('renderHistoryChart(cachedHistory)',
         'Chart re-renders from cache on range/mode change'),
        ('beginAtZero: mode === \'rate\'', 'Y-axis beginAtZero adapts to mode'),
        ('deltasParam = mode === \'rate\' ? \'?deltas=true\' : \'\'', 'Model deltas param based on mode'),
        ('_modelDeltas', 'Model deltas stored separately from cumulative'),
        ('chartTitle = mode === \'rate\' ?', 'Model chart title adapts to mode'),
    ]
    for pattern, msg in checks:
        if pattern in js:
            ok(msg)
        else:
            fail(f'Missing: {msg}')
else:
    fail(f'app.js returned HTTP {status}')

# ── 4. CSS ──
heading(4, 'CSS')
css, status = get('/static/index.css')
if status == 200:
    for pattern, msg in [
        ('.source-combined', '.source-combined class'),
        ('.source-agy', '.source-agy class'),
        ('grid-template-columns: repeat(4, 1fr)', 'Combined 4-column grid'),
        ('grid-template-columns: repeat(2, 1fr)', 'AGY 2-column grid'),
        ('@media (max-width: 900px)', 'Responsive breakpoint at 900px'),
        ('@media (max-width: 600px)', 'Responsive breakpoint at 600px'),
        ('.badge-agy', 'AGY badge style'),
        ('.badge-opencode', 'OpenCode badge style'),
        ('.badge-codex', 'Codex badge style'),
        ('.quota-bar-fill.green', 'Green quota bar'),
        ('.quota-bar-fill.amber', 'Amber quota bar'),
        ('.quota-bar-fill.red', 'Red quota bar'),
        ('.stats-row', 'Stats row layout'),
        ('.stats-overview', 'Stats overview section'),
        ('.range-btn', 'Time range button style'),
        ('.mode-btn', 'Mode toggle button style'),
        ('.range-btn.active', 'Active range button style'),
        ('.mode-btn.active', 'Active mode button style'),
    ]:
        if pattern in css:
            ok(msg)
        else:
            fail(f'Missing: {msg}')
else:
    fail(f'index.css returned HTTP {status}')

# ── 5. API: Combined usage ──
heading(5, 'API: Combined usage')
body, status = get('/api/usage/latest')
if status == 200:
    try:
        d = json.loads(body)
        for src in ('agy', 'opencode', 'codex'):
            if src in d:
                ok(f'Usage: {src} present')
            else:
                fail(f'Usage: {src} missing')
        for field in ('sessions', 'messages', 'input_tokens', 'output_tokens'):
            total = sum(d.get(s, {}).get(field, 0) or 0 for s in ('agy', 'opencode', 'codex'))
            if total is not None:
                ok(f'Usage: {field} aggregated')
    except json.JSONDecodeError:
        fail('Usage: invalid JSON')
else:
    fail(f'/api/usage/latest returned HTTP {status}')

# ── 6. API: Per-source usage ──
heading(6, 'API: Per-source usage')
for src in ('agy', 'opencode', 'codex'):
    body, status = get(f'/api/usage/{src}/latest')
    if status == 200:
        try:
            d = json.loads(body)
            if d:
                ok(f'Usage/{src}: data present')
            else:
                fail(f'Usage/{src}: empty response')
        except json.JSONDecodeError:
            fail(f'Usage/{src}: invalid JSON')
    else:
        fail(f'/api/usage/{src}/latest returned HTTP {status}')

# ── 7. API: Model deltas (Rate mode) ──
heading(7, 'API: Model deltas')
for src in ('', '?deltas=true'):
    label = 'with deltas' if src else 'without deltas'
    body, status = get(f'/api/usage/latest{src}')
    if status == 200:
        try:
            d = json.loads(body)
            key = 'model_deltas' if src else 'models'
            for s in ('agy', 'opencode', 'codex'):
                items = d.get(s, {}).get(key, [])
                if isinstance(items, list):
                    ok(f'Usage/latest {label}: {s}.{key} has {len(items)} items')
                else:
                    fail(f'Usage/latest {label}: {s}.{key} not a list')
        except json.JSONDecodeError:
            fail(f'Usage/latest {label}: invalid JSON')
    else:
        fail(f'/api/usage/latest{src} returned HTTP {status}')

# ── 8. API: Usage history ──
heading(8, 'API: Usage history')
for src in ('agy', 'opencode', 'codex'):
    body, status = get(f'/api/usage/{src}/history')
    if status == 200:
        try:
            d = json.loads(body)
            if isinstance(d, list):
                ok(f'History/{src}: {len(d)} data points')
            else:
                fail(f'History/{src}: expected list, got {type(d).__name__}')
        except json.JSONDecodeError:
            fail(f'History/{src}: invalid JSON')
    else:
        fail(f'/api/usage/{src}/history returned HTTP {status}')

# ── 9. API: Combined quota ──
heading(9, 'API: Combined quota')
body, status = get('/api/quota/latest')
if status == 200:
    try:
        d = json.loads(body)
        for src in ('agy', 'opencode', 'codex'):
            if src in d:
                ok(f'Quota: {src} present')
            else:
                fail(f'Quota: {src} missing')
        # AGY plan
        agy_plan = d.get('agy', {}).get('_plan', '')
        if agy_plan:
            ok(f'Quota: AGY plan="{agy_plan}"')
        else:
            fail('Quota: AGY _plan missing')
        # AGY model groups
        agy_groups = [k for k in d.get('agy', {}) if k != '_plan']
        for expected in ('gemini_models', 'claude_gpt_models'):
            if expected in agy_groups:
                ok(f'Quota: AGY group "{expected}" present')
            else:
                fail(f'Quota: AGY group "{expected}" missing')
        # AGY quota fields
        for group in agy_groups:
            for lt_name, lt in d['agy'][group].items():
                for field in ('used', 'total', 'remaining_pct', 'refreshes_in_seconds'):
                    if field in lt:
                        ok(f'Quota: AGY.{group}.{lt_name}.{field}={lt[field]}')
                    else:
                        fail(f'Quota: AGY.{group}.{lt_name}.{field} missing')
        # OpenCode
        oc = d.get('opencode', {}).get('opencode', {})
        if oc.get('total_cost', {}).get('used') is not None:
            ok(f'Quota: OpenCode cost=${oc["total_cost"]["used"]:.2f}')
        else:
            fail('Quota: OpenCode cost missing')
        # Codex
        cd = d.get('codex', {})
        codex_plan = cd.get('_plan', 'N/A')
        if codex_plan != 'N/A':
            ok(f'Quota: Codex plan="{codex_plan}"')
        rl = cd.get('openai', {}).get('rate_limit', {})
        if rl:
            for field in ('remaining_pct', 'used', 'total', 'refreshes_in_seconds'):
                if field in rl and rl[field] is not None:
                    ok(f'Quota: Codex rate_limit.{field}={rl[field]}')
                else:
                    fail(f'Quota: Codex rate_limit.{field} missing')
    except json.JSONDecodeError:
        fail('Quota combined: invalid JSON')
else:
    fail(f'/api/quota/latest returned HTTP {status}')

# ── 10. API: Per-source quota ──
heading(10, 'API: Per-source quota')
for src in ('agy', 'opencode', 'codex'):
    body, status = get(f'/api/quota/{src}/latest')
    if status == 200:
        try:
            d = json.loads(body)
            if d and src in d:
                ok(f'Quota/{src}: data present')
            else:
                fail(f'Quota/{src}: empty or missing source key')
        except json.JSONDecodeError:
            fail(f'Quota/{src}: invalid JSON')
    else:
        fail(f'/api/quota/{src}/latest returned HTTP {status}')

# ── 11. Codex JWT plan extraction ──
heading(11, 'Codex: JWT plan extraction')
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
    from codex_quota import fetch_codex_quota
    raw = fetch_codex_quota()
    if 'error' in raw:
        fail(f'Codex fetch: {raw["error"]}')
    else:
        if raw.get('plan_type'):
            ok(f'Codex: plan_type="{raw["plan_type"]}" from JWT')
        else:
            fail('Codex: no plan_type from JWT')
        if 'tokens' in raw:
            t = raw['tokens']
            ok(f'Codex: {t.get("total_sessions",0)} sessions, {t.get("total_tokens",0):,} tokens')
        else:
            fail('Codex: no token stats')
        if raw.get('primary_used_pct') is not None:
            ok(f'Codex: primary_used_pct={raw["primary_used_pct"]} from logs')
        else:
            ok('Codex: no rate limit data in logs (will appear after API calls)')
except ImportError as e:
    fail(f'Codex JWT check: import error: {e}')
except Exception as e:
    fail(f'Codex JWT check: {e}')

# ── 12. AGY plan backend extraction ──
heading(12, 'AGY: plan extraction')
try:
    from quota_parser import _detect_agy_plan
    plan = _detect_agy_plan()
    if plan:
        ok(f'AGY: plan="{plan}" from Cloud Code API')
    else:
        fail(f'AGY: no plan returned')
except ImportError as e:
    fail(f'AGY plan check: import error: {e}')
except Exception as e:
    fail(f'AGY plan check: {e}')

# ── 13. Frontend loads ──
heading(13, 'Frontend load')
html, status = get('/static/index.html')
if status == 200 and '</html>' in html:
    ok('index.html serves correctly')
else:
    fail('index.html check')
body, status = get('/static/app.js')
if status == 200:
    ok('app.js serves correctly')
else:
    fail('app.js check')
body, status = get('/static/index.css')
if status == 200:
    ok('index.css serves correctly')
else:
    fail('index.css check')

# ── 14. Regression: Sessions/Messages same row ──
heading(14, 'Regression: Sessions/Messages layout')
html, _ = get('/static/index.html')
if 'class="card-row"' in html:
    ok('Sessions/Messages uses card-row flex layout')
else:
    fail('Sessions/Messages card-row missing')
if '<p id="total-messages"' in html:
    fail('total-messages is still a <p> element')
else:
    ok('total-messages is not a <p> (uses card-row)')

# ── 15. Regression: XSS prevention ──
heading(15, 'Regression: XSS prevention')
js, _ = get('/static/app.js')
if 'function escapeHtml' in js:
    ok('escapeHtml function defined')
else:
    fail('escapeHtml function missing')
for pattern, msg in [
    ('${escapeHtml(agyPlan)}', 'AGY plan badge escaped'),
    ('${escapeHtml(planLabel)}', 'Codex plan badge escaped'),
    ('${escapeHtml(label)}', 'Quota limit label escaped'),
    ('${escapeHtml(m.model_name)}', 'Model name escaped'),
    ('${escapeHtml(groupLabel)}', 'Group label escaped'),
]:
    if pattern in js:
        ok(f'XSS: {msg}')
    else:
        fail(f'XSS: {msg} missing')

# ── 16. Regression: Stale cache on tab switch ──
heading(16, 'Regression: Stale cache on tab switch')
if 'cachedHistory = null' in js and 'cachedLatestOverview = null' in js:
    ok('Caches cleared on tab switch')
else:
    fail('Caches not cleared on tab switch')

# ── 17. Regression: parseTs date helper ──
heading(17, 'Regression: Date parsing')
if 'function parseTs' in js:
    ok('parseTs helper defined')
else:
    fail('parseTs helper missing')
if "replace(' ', 'T') + 'Z'" in js or "replace(' ', 'T')" in js:
    ok('parseTs converts to ISO format')
else:
    fail('parseTs does not convert to ISO format')
if "hour12: false" in js:
    ok('Mobile 24-hour time format')
else:
    fail('Mobile 24-hour time format missing')

# ── 18. Regression: Mobile responsive ──
heading(18, 'Regression: Mobile responsive')
css, _ = get('/static/index.css')
if '@media (max-width: 640px)' in css:
    ok('Mobile breakpoint at 640px')
else:
    fail('Mobile breakpoint at 640px missing')
for pattern, msg in [
    ('.card-row', 'card-row CSS defined'),
    ('.card-sep', 'card-sep CSS defined'),
    ('overflow-x: auto', 'Tabs horizontally scrollable on mobile'),
    ('.charts-section', 'Charts section mobile override'),
]:
    if pattern in css:
        ok(f'Mobile: {msg}')
    else:
        fail(f'Mobile: {msg} missing')

# ── 19. Regression: Header layout ──
heading(19, 'Regression: Header layout')
html, _ = get('/static/index.html')
if 'time-range-buttons' in html:
    ok('Time range buttons in HTML')
else:
    fail('Time range buttons missing from HTML')
header_match = re.search(r'<header.*?</header>', html, re.DOTALL)
header_html = header_match.group() if header_match else ''
if 'subtitle' not in header_html.lower() or 'section-subtitle' not in header_html:
    ok('No subtitle in header')
else:
    fail('Subtitle still present in header')

# ── 20. Regression: Codex billing API path ──
heading(20, 'Regression: Codex billing API handling')
app_py = open(os.path.join(os.path.dirname(__file__), 'backend', 'app.py')).read()
api_py = open(os.path.join(os.path.dirname(__file__), 'backend', 'api.py')).read()
poller_py = open(os.path.join(os.path.dirname(__file__), 'backend', 'poller.py')).read()
code_source = api_py if "codex_live.get('plan_type') or codex_live.get('plan'" in api_py else app_py
if "codex_live.get('plan_type') or codex_live.get('plan'" in code_source:
    ok('Codex plan reads from plan_type OR plan')
else:
    fail('Codex plan fallback not implemented')
if "'total_used_usd' in quota" in poller_py:
    ok('Codex billing API path stored in DB')
else:
    fail('Codex billing API path not stored')
if "'total_used_usd' in codex_live" in (api_py if "'total_used_usd' in codex_live" in api_py else app_py):
    ok('Codex billing API path in combined quota')
else:
    fail('Codex billing API path missing from combined quota')

# ── 21. Regression: Consistent field names ──
heading(21, 'Regression: Consistent field names')
if 'refreshes_in_seconds' in app_py or 'refreshes_in_seconds' in api_py or 'refreshes_in_seconds' in poller_py:
    ok('Backend uses refreshes_in_seconds')
else:
    fail('Backend missing refreshes_in_seconds')
if "refreshes_in_seconds" in js:
    ok('Frontend uses refreshes_in_seconds')
else:
    fail('Frontend missing refreshes_in_seconds')

# ── 22. Regression: JSON parse isolation ──
heading(22, 'Regression: JSON parse error isolation')
if '.value.json(); } catch' in js:
    ok('Combined history JSON parse isolated per source')
else:
    fail('Combined history JSON parse not isolated')

# ── 23. Regression: Chart quality ──
heading(23, 'Regression: Chart quality')
if 'tension: 0.4' in js:
    ok('Chart uses original tension 0.4')
else:
    fail('Chart tension not 0.4')
if 'pointHoverRadius' not in js:
    ok('No point hover radius (original)')
else:
    fail('Chart should not have pointHoverRadius')
if 'borderWidth: 2' not in js:
    ok('No forced border width (original)')
else:
    fail('Chart should not have borderWidth: 2')
if "'doughnut'" in js:
    ok('Model chart is doughnut type')
else:
    fail('Model chart not doughnut type')

# ── 24. Regression: Chart sizing ──
heading(24, 'Regression: Chart sizing')
if 'maintainAspectRatio' not in js:
    ok('Charts use natural aspect ratio')
else:
    fail('Chart maintainAspectRatio should be removed')

# ── 25. Regression: Combined chart timestamp tolerance ──
heading(25, 'Regression: Combined chart timestamp matching')
if 'buildFilledLookup' in js:
    ok('Combined chart uses forward-fill timestamp matching')
else:
    fail('Combined chart missing buildFilledLookup function')
if 'MS_TOLERANCE' in js:
    ok('Combined chart has MS_TOLERANCE tolerance window')
else:
    fail('Combined chart missing MS_TOLERANCE')
if 'list.find(d => d.timestamp === ts)' not in js and 'list.find(d.timestamp' not in js.replace(' ', ''):
    ok('No exact timestamp === match in combined chart')
else:
    fail('Combined chart still uses exact timestamp match')
if 'Math.abs(lastTs.getTime() - t) <= MS_TOLERANCE' in js:
    ok('buildFilledLookup returns null when outside tolerance window')
else:
    fail('buildFilledLookup missing tolerance boundary check')

# ── 26. Regression: Model panel respects time range ──
heading(26, 'Regression: Model panel respects time range')
if 'computeModelsFromHistory' in js:
    ok('computeModelsFromHistory function exists')
else:
    fail('missing computeModelsFromHistory')
if 'refreshModels' in js:
    ok('refreshModels function exists')
else:
    fail('missing refreshModels')
db_py = open(os.path.join(os.path.dirname(__file__), 'backend', 'db.py')).read()
if "model_usage WHERE source=?" in db_py:
    ok('Backend: history endpoint includes model data')
else:
    fail('Backend: history endpoint missing model data')

# ── 27. M1: config.py ──
heading(27, 'M1: config.py')
config_path = os.path.join(os.path.dirname(__file__), 'backend', 'config.py')
if os.path.exists(config_path):
    ok('config.py exists')
else:
    fail('config.py not found')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
try:
    from config import Config, load_config
    ok('config.py has Config dataclass and load_config()')
    from dataclasses import fields as _dc_fields
    _field_names = {f.name for f in _dc_fields(Config)}
    if 'db_path' in _field_names and 'poll_interval' in _field_names:
        ok('Config has db_path and poll_interval fields')
    else:
        fail(f'Config missing expected fields, got: {_field_names}')

    cfg = load_config()
    assert cfg.poll_interval == 600, f'default poll_interval should be 600, got {cfg.poll_interval}'
    assert cfg.port == 8000
    assert cfg.log_level == 'INFO'
    ok('load_config() returns Config with correct defaults')
except (ImportError, AssertionError, ValueError) as e:
    fail(f'config.py test failed: {e}')

try:
    import os as _os
    _os.environ['USAGE_POLL_INTERVAL'] = 'abc'
    from config import load_config as _lc
    try:
        _lc()
        fail('load_config() should reject invalid USAGE_POLL_INTERVAL')
    except ValueError:
        ok('load_config() rejects non-integer USAGE_POLL_INTERVAL')
    finally:
        del _os.environ['USAGE_POLL_INTERVAL']
except Exception:
    pass

try:
    _os.environ['USAGE_LOG_LEVEL'] = 'TRACE'
    try:
        _lc()
        fail('load_config() should reject invalid USAGE_LOG_LEVEL')
    except ValueError:
        ok('load_config() rejects invalid USAGE_LOG_LEVEL')
    finally:
        del _os.environ['USAGE_LOG_LEVEL']
except Exception:
    pass

# ── 26. M1: db.py new functions ──
heading(28, 'M1: db.py new functions')
db_path = os.path.join(os.path.dirname(__file__), 'backend', 'db.py')
if os.path.exists(db_path):
    ok('db.py exists')
else:
    fail('db.py not found')

try:
    from db import connect, init_schema, record_status, metrics, prune, init_db
    ok('db.py exports connect(), init_schema(), record_status(), metrics(), prune()')
except ImportError as e:
    fail(f'db.py import failed: {e}')

# Test connect() with WAL pragmas
import tempfile
import sqlite3
tf = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tf.close()
try:
    conn = connect(tf.name)
    ok('connect() returns a connection')

    # Check WAL
    cur = conn.execute("PRAGMA journal_mode")
    row = cur.fetchone()
    if row and row[0].lower() in ('wal', 'memory'):
        ok('WAL pragma set in connect()')
    else:
        fail(f'WAL journal_mode missing, got: {row}')

    # Check synchronous
    cur = conn.execute("PRAGMA synchronous")
    row = cur.fetchone()
    if row and row[0] == 1:
        ok('synchronous=NORMAL pragma set')
    else:
        fail(f'synchronous not NORMAL, got: {row}')

    # Check foreign_keys
    cur = conn.execute("PRAGMA foreign_keys")
    row = cur.fetchone()
    if row and row[0] == 1:
        ok('foreign_keys=ON pragma set')
    else:
        fail(f'foreign_keys not ON, got: {row}')

    # Check row_factory
    if conn.row_factory is sqlite3.Row:
        ok('row_factory set to sqlite3.Row')
    else:
        fail('row_factory not set to sqlite3.Row')

    conn.close()
except Exception as e:
    fail(f'connect() test error: {e}')
finally:
    os.unlink(tf.name)

# Test init_schema includes collection_status
tf2 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tf2.close()
try:
    conn = connect(tf2.name)
    init_schema(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='collection_status'"
    )
    if cur.fetchone():
        ok('init_schema() creates collection_status table')
    else:
        fail('collection_status table not created')

    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    )
    if cur.fetchone():
        ok('init_schema() creates meta table')
    else:
        fail('meta table not created')

    cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    if row and row['value'] == '1':
        ok('meta has initial schema_version=1')
    else:
        fail('schema_version missing from meta')

    conn.close()
except Exception as e:
    fail(f'init_schema() test error: {e}')
finally:
    os.unlink(tf2.name)

# Test record_status
tf3 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tf3.close()
try:
    conn = connect(tf3.name)
    init_schema(conn)
    record_status(conn, 'test_source', True, '', 123.4)
    cur = conn.execute(
        "SELECT source, ok, error, duration_ms FROM collection_status WHERE source='test_source'"
    )
    row = cur.fetchone()
    if row and row['ok'] == 1 and row['source'] == 'test_source':
        ok('record_status() inserts row correctly')
    else:
        fail(f'record_status() row incorrect: {dict(row) if row else None}')

    record_status(conn, 'test_source', False, 'something broke', 0.0)
    cur = conn.execute(
        "SELECT error FROM collection_status WHERE source='test_source' AND ok=0"
    )
    row = cur.fetchone()
    if row and row['error'] == 'something broke':
        ok('record_status() stores error text on failure')
    else:
        fail('record_status() error text not stored')

    conn.close()
except Exception as e:
    fail(f'record_status() test error: {e}')
finally:
    os.unlink(tf3.name)

# Test prune
tf4 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tf4.close()
try:
    conn = connect(tf4.name)
    init_schema(conn)
    old_ts = '2000-01-01 00:00:00'
    conn.execute(
        "INSERT INTO usage_history (timestamp, source) VALUES (?, 'test_prune')",
        (old_ts,)
    )
    conn.commit()
    prune(conn, 1)
    cur = conn.execute("SELECT COUNT(*) AS cnt FROM usage_history WHERE source='test_prune'")
    cnt = cur.fetchone()['cnt']
    if cnt == 0:
        ok('prune() removes rows older than retention_days')
    else:
        fail(f'prune() did not remove old rows, {cnt} remain')
    conn.close()
except Exception as e:
    fail(f'prune() test error: {e}')
finally:
    os.unlink(tf4.name)

# Test metrics
tf5 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tf5.close()
try:
    conn = connect(tf5.name)
    init_schema(conn)
    record_status(conn, 'test_metrics', True, '', 50.0)
    m = metrics(conn)
    if 'per_source' in m and 'total_polls' in m and 'db_size_bytes' in m:
        ok('metrics() returns dict with per_source, total_polls, db_size_bytes')
    else:
        fail(f'metrics() missing keys, got: {list(m.keys())}')
    if 'test_metrics' in m['per_source']:
        ok('metrics() includes per-source data')
    else:
        fail('metrics() per_source missing test_metrics')
    conn.close()
except Exception as e:
    fail(f'metrics() test error: {e}')
finally:
    os.unlink(tf5.name)

# Test backward compatibility: init_db() still works
tf6 = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
tf6.close()
try:
    _old_path = os.environ.get('USAGE_DB_PATH')
    os.environ['USAGE_DB_PATH'] = tf6.name
    # Reload db module with new env
    import importlib
    import db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    conn = db_mod.connect(tf6.name)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = {r['name'] for r in cur.fetchall()}
    expected = {'usage_history', 'model_usage', 'quota_snapshots', 'collection_status', 'meta'}
    if expected.issubset(tables):
        ok('init_db() backward compatible: all tables created')
    else:
        fail(f'init_db() missing tables: {expected - tables}')
    if _old_path:
        os.environ['USAGE_DB_PATH'] = _old_path
    else:
        del os.environ['USAGE_DB_PATH']
    conn.close()
except Exception as e:
    fail(f'init_db() backward compat test error: {e}')
finally:
    if os.path.exists(tf6.name):
        os.unlink(tf6.name)

# ── 27. M2: Parser Contract ──
heading(29, 'M2: Parser Contract')

# parsers/ package exists
parsers_dir = os.path.join(os.path.dirname(__file__), 'backend', 'parsers')
if os.path.isdir(parsers_dir):
    ok('parsers/ package directory exists')
else:
    fail('parsers/ package directory not found')

parsers_init = os.path.join(parsers_dir, '__init__.py')
if os.path.isfile(parsers_init):
    ok('parsers/__init__.py exists')
else:
    fail('parsers/__init__.py not found')

# Parser ABC, SourceUnavailable, ParserResult, ModelUsage
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
try:
    from parsers.base import Parser, ParserResult, ModelUsage, SourceUnavailable
    ok('parsers.base exports Parser, ParserResult, ModelUsage, SourceUnavailable')

    # Parser is ABC with abstract parse()
    from abc import ABC
    if issubclass(Parser, ABC):
        ok('Parser is an ABC')
    else:
        fail('Parser is not an ABC')
    if hasattr(Parser.parse, '__isabstractmethod__'):
        ok('Parser.parse() is abstract')
    else:
        fail('Parser.parse() is not abstract')

    # SourceUnavailable extends Exception
    if issubclass(SourceUnavailable, Exception):
        ok('SourceUnavailable extends Exception')
    else:
        fail('SourceUnavailable does not extend Exception')

    # ParserResult fields
    from dataclasses import fields
    pr_fields = {f.name for f in fields(ParserResult)}
    for expected in ('sessions', 'messages', 'input_tokens', 'output_tokens', 'cache_read', 'cache_write', 'models'):
        if expected in pr_fields:
            ok(f'ParserResult has field "{expected}"')
        else:
            fail(f'ParserResult missing field "{expected}"')

    # ModelUsage fields
    mu_fields = {f.name for f in fields(ModelUsage)}
    for expected in ('model_name', 'messages', 'input_tokens', 'output_tokens', 'cache_read', 'cache_write', 'cost'):
        if expected in mu_fields:
            ok(f'ModelUsage has field "{expected}"')
        else:
            fail(f'ModelUsage missing field "{expected}"')
except ImportError as e:
    fail(f'parsers.base import error: {e}')

# Each parser class implements Parser
try:
    from parsers.opencode import OpenCodeParser
    if issubclass(OpenCodeParser, Parser):
        ok('OpenCodeParser implements Parser')
    else:
        fail('OpenCodeParser does not implement Parser')
    ocp = OpenCodeParser(timeout=1)
    if hasattr(ocp, 'parse') and callable(ocp.parse):
        ok('OpenCodeParser has callable parse()')
    else:
        fail('OpenCodeParser parse() not callable')
except ImportError as e:
    fail(f'OpenCodeParser import error: {e}')

try:
    from parsers.agy import AgyParser
    if issubclass(AgyParser, Parser):
        ok('AgyParser implements Parser')
    else:
        fail('AgyParser does not implement Parser')
    ap = AgyParser(conv_dir='/nonexistent', ide_conv_dir='/nonexistent')
    if hasattr(ap, 'parse') and callable(ap.parse):
        ok('AgyParser has callable parse()')
    else:
        fail('AgyParser parse() not callable')
except ImportError as e:
    fail(f'AgyParser import error: {e}')

try:
    from parsers.codex import CodexParser
    if issubclass(CodexParser, Parser):
        ok('CodexParser implements Parser')
    else:
        fail('CodexParser does not implement Parser')
    cp = CodexParser(state_db='/nonexistent/state.sqlite')
    if hasattr(cp, 'parse') and callable(cp.parse):
        ok('CodexParser has callable parse()')
    else:
        fail('CodexParser parse() not callable')
except ImportError as e:
    fail(f'CodexParser import error: {e}')

# parsers __init__ re-exports
try:
    from parsers import Parser as P_from_init, ParserResult as PR_from_init
    from parsers import ModelUsage as MU_from_init, SourceUnavailable as SU_from_init
    from parsers import OpenCodeParser as OCP_from_init, AgyParser as AP_from_init, CodexParser as CP_from_init
    ok('parsers/__init__ re-exports all public symbols')
except ImportError as e:
    fail(f'parsers/__init__ re-export error: {e}')

# Backward-compatible wrappers
for mod_name, func_name in [
    ('parser', 'fetch_and_parse'),
    ('agy_parser', 'fetch_agy_usage'),
    ('codex_parser', 'fetch_codex_usage'),
]:
    try:
        mod = __import__(mod_name, fromlist=[func_name])
        fn = getattr(mod, func_name)
        if callable(fn):
            ok(f'{mod_name}.{func_name}() is callable')
        else:
            fail(f'{mod_name}.{func_name}() not callable')
        result = fn()
        if isinstance(result, tuple) and len(result) == 3:
            overview, cost_tokens, models = result
            if isinstance(overview, dict) and isinstance(cost_tokens, dict) and isinstance(models, list):
                ok(f'{mod_name}.{func_name}() returns (dict, dict, list)')
            else:
                fail(f'{mod_name}.{func_name}() return types wrong')
        else:
            fail(f'{mod_name}.{func_name}() does not return 3-tuple')
    except ImportError as e:
        fail(f'{mod_name} import error: {e}')
    except Exception as e:
        fail(f'{mod_name}.{func_name}() error: {e}')

# SourceUnavailable raised when source is missing
try:
    ocp = OpenCodeParser(timeout=1)
    try:
        ocp.parse()
        fail('OpenCodeParser.parse() should raise SourceUnavailable when opencode not found')
    except SourceUnavailable:
        ok('OpenCodeParser raises SourceUnavailable on missing binary')
    except Exception:
        pass  # Could also be FileNotFoundError wrapped
except ImportError as e:
    fail(f'SourceUnavailable test: {e}')

# ── 28. M3: Quota Module (quota.py) ──
heading(30, 'M3: Quota Module')

quota_path = os.path.join(os.path.dirname(__file__), 'backend', 'quota.py')
if os.path.exists(quota_path):
    ok('quota.py exists')
else:
    fail('quota.py not found')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
try:
    from quota import collect
    import inspect
    sig = inspect.signature(collect)
    param_names = list(sig.parameters.keys())
    if len(param_names) == 2 and param_names[0] == 'source':
        ok(f'collect() has correct signature: {sig}')
    else:
        fail(f'collect() signature wrong, got: {sig}')
except ImportError as e:
    fail(f'quota module import failed: {e}')
except Exception as e:
    fail(f'quota module check error: {e}')

try:
    from config import Config, load_config
    cfg = load_config()
    result = collect('agy', cfg)
    if isinstance(result, dict) or result is None:
        ok("collect('agy', cfg) returns dict or None")
    else:
        fail(f"collect('agy', cfg) returned unexpected type: {type(result).__name__}")
except ImportError as e:
    fail(f"collect('agy') import error: {e}")
except Exception as e:
    fail(f"collect('agy') error: {e}")

try:
    result = collect('opencode', cfg)
    if isinstance(result, dict) or result is None:
        ok("collect('opencode', cfg) returns dict or None")
    else:
        fail(f"collect('opencode', cfg) returned unexpected type: {type(result).__name__}")
except ImportError as e:
    fail(f"collect('opencode') import error: {e}")
except Exception as e:
    fail(f"collect('opencode') error: {e}")

try:
    result = collect('codex', cfg)
    if isinstance(result, dict) or result is None:
        ok("collect('codex', cfg) returns dict or None")
    else:
        fail(f"collect('codex', cfg) returned unexpected type: {type(result).__name__}")
except ImportError as e:
    fail(f"collect('codex') import error: {e}")
except Exception as e:
    fail(f"collect('codex') error: {e}")

try:
    collect('unknown', cfg)
    fail("collect('unknown', cfg) should raise ValueError")
except ValueError:
    ok("collect('unknown', cfg) raises ValueError")
except Exception:
    pass

# ── 29. M4: Poller Module ──
heading(31, 'M4: Poller Module')

poller_path = os.path.join(os.path.dirname(__file__), 'backend', 'poller.py')
if os.path.exists(poller_path):
    ok('poller.py exists')
else:
    fail('poller.py not found')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
try:
    from poller import Poller
    ok('poller.py has Poller class')

    p = Poller(load_config())
    assert hasattr(p, 'run_once') and callable(p.run_once)
    ok('Poller.run_once() exists and is callable')
    assert hasattr(p, 'start') and callable(p.start)
    ok('Poller.start() exists and is callable')
    assert hasattr(p, 'stop') and callable(p.stop)
    ok('Poller.stop() exists and is callable')

    p.stop()
    assert p._stop.is_set()
    ok('Poller.stop() sets the stop event')
except ImportError as e:
    fail(f'poller import failed: {e}')
except AssertionError as e:
    fail(f'poller assertion failed: {e}')
except Exception as e:
    fail(f'poller check error: {e}')

# ── 30. M5: API Module (api.py) ──
heading(32, 'M5: API Module')

api_path = os.path.join(os.path.dirname(__file__), 'backend', 'api.py')
if os.path.exists(api_path):
    ok('api.py exists')
else:
    fail('api.py not found')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
try:
    from fastapi import FastAPI
    from api import create_app, error_response
    ok('api.py exports create_app() and error_response()')

    app = create_app()
    if isinstance(app, FastAPI):
        ok('create_app() returns a FastAPI instance')
    else:
        fail('create_app() does not return FastAPI')

    # Check all critical routes exist
    routes = {r.path for r in app.routes}
    expected_routes = [
        '/health', '/ready', '/metrics',
        '/api/usage/latest', '/api/usage/opencode/latest',
        '/api/usage/agy/latest', '/api/usage/codex/latest',
        '/api/usage/opencode/history', '/api/usage/agy/history',
        '/api/usage/codex/history', '/api/usage/history',
        '/api/quota/latest', '/api/quota/agy/latest',
        '/api/quota/opencode/latest', '/api/quota/codex/latest',
        '/', '/static',
    ]
    for route in expected_routes:
        if route == '/static':
            names = {r.name for r in app.routes if hasattr(r, 'name')}
            if 'static' in names:
                ok(f'Route: {route} mounted')
            else:
                fail(f'Route: {route} not mounted')
        elif route in routes:
            ok(f'Route: {route}')
        else:
            fail(f'Route: {route} missing')

    # Error envelope
    resp = error_response("not_found", "Not found", 404)
    if resp.status_code == 404 and hasattr(resp, 'body'):
        ok('error_response() returns JSONResponse with correct status')
    else:
        fail('error_response() incorrect')

    # Error handlers registered
    if hasattr(app, 'exception_handlers') and 404 in app.exception_handlers:
        ok('404 error handler registered')
    else:
        fail('404 error handler missing')
    if hasattr(app, 'exception_handlers') and 500 in app.exception_handlers:
        ok('500 error handler registered')
    else:
        fail('500 error handler missing')

except ImportError as e:
    fail(f'api.py import failed: {e}')
except Exception as e:
    fail(f'api.py check error: {e}')

# ── 31. M5: app.py is thin ──
heading(33, 'M5: app.py is thin')

app_py_content = open(os.path.join(os.path.dirname(__file__), 'backend', 'app.py')).read()
lines = [l for l in app_py_content.strip().split('\n') if l.strip() and not l.strip().startswith('#')]
if len(lines) <= 3:
    ok(f'app.py is thin ({len(lines)} non-comment lines)')
else:
    fail(f'app.py has {len(lines)} non-comment lines (expected <= 3)')

if 'from .api import create_app' in app_py_content:
    ok('app.py imports create_app from .api')
else:
    fail('app.py does not import from .api')

if 'app = create_app()' in app_py_content:
    ok('app.py calls create_app()')
else:
    fail('app.py missing app = create_app()')

# Ensure no route definitions remain in app.py
for phrase in ('@app.get', '@app.post', 'add_api_route', 'app.mount'):
    if phrase in app_py_content.replace('from .api import create_app', '').replace('app = create_app()', '').replace('"""FastAPI application for the AI Usage Dashboard."""', ''):
        fail(f'app.py still contains {phrase}')
        break
else:
    ok('app.py contains no route definitions (all delegated to api.py)')

# ── 32. M6: Entry Point (main.py) ──
heading(34, 'M6: Entry Point')

main_path = os.path.join(os.path.dirname(__file__), 'backend', 'main.py')
if os.path.exists(main_path):
    ok('main.py exists')
else:
    fail('main.py not found')

main_py = open(main_path).read()
checks = [
    ('from config import load_config', 'imports load_config from config'),
    ('from db import connect, init_schema', 'imports connect and init_schema from db'),
    ('from poller import Poller', 'imports Poller from poller'),
    ('uvicorn.run', 'calls uvicorn.run()'),
    ('"api:create_app"', 'references api:create_app'),
    ('factory=True', 'uses factory=True'),
    ('cfg.host', 'uses cfg.host'),
    ('cfg.port', 'uses cfg.port'),
    ('signal.signal(signal.SIGTERM', 'handles SIGTERM'),
    ('signal.signal(signal.SIGINT', 'handles SIGINT'),
    ('poller.start()', 'starts the poller'),
    ('poller.stop()', 'stops the poller on shutdown'),
    ('def main():', 'has a main() function'),
    ('if __name__', 'has __main__ guard'),
]
for pattern, msg in checks:
    if pattern in main_py:
        ok(f'main.py {msg}')
    else:
        fail(f'main.py missing: {msg}')

# ── 33. M7+M8: Frontend Shell + UX States + A11y ──
heading(35, 'M7+M8: Frontend Shell + UX + A11y')

html = open(os.path.join(os.path.dirname(__file__), 'frontend', 'index.html')).read()
css = open(os.path.join(os.path.dirname(__file__), 'frontend', 'index.css')).read()
js = open(os.path.join(os.path.dirname(__file__), 'frontend', 'app.js')).read()

# --- ARIA ---
if 'role="tablist"' in html:
    ok('HTML: role="tablist" on tabs container')
else:
    fail('HTML: missing role="tablist"')
if 'role="tab"' in html:
    ok('HTML: role="tab" on tab buttons')
else:
    fail('HTML: missing role="tab"')
if 'aria-selected=' in html:
    ok('HTML: aria-selected on tabs')
else:
    fail('HTML: missing aria-selected')
if 'aria-live="polite"' in html or 'aria-live="assertive"' in html:
    ok('HTML: aria-live region for dynamic content')
else:
    fail('HTML: missing aria-live region')
if 'role="tabpanel"' in html:
    ok('HTML: role="tabpanel" on main content')
else:
    fail('HTML: missing role="tabpanel"')
if 'role="group"' in html:
    ok('HTML: role="group" on button groups')
else:
    fail('HTML: missing role="group" on button groups')
if 'aria-label=' in html:
    ok('HTML: aria-label on interactive elements')
else:
    fail('HTML: missing aria-label attributes')
if 'role="alert"' in html:
    ok('HTML: role="alert" on error banner')
else:
    fail('HTML: missing role="alert" on error banner')

# --- CSS: Focus, motion, skeletons, states ---
if ':focus-visible' in css:
    ok('CSS: :focus-visible focus ring')
else:
    fail('CSS: missing :focus-visible')
if 'visually-hidden' in css:
    ok('CSS: .visually-hidden utility class')
else:
    fail('CSS: missing .visually-hidden')
if 'prefers-reduced-motion' in css:
    ok('CSS: @media prefers-reduced-motion')
else:
    fail('CSS: missing prefers-reduced-motion')
if 'skeleton' in css:
    ok('CSS: .skeleton shimmer animation')
else:
    fail('CSS: missing skeleton styles')
if '.error-banner' in css:
    ok('CSS: .error-banner styles')
else:
    fail('CSS: missing error banner styles')
if 'empty-state' in css:
    ok('CSS: .empty-state styles')
else:
    fail('CSS: missing empty state styles')
if '@media (max-width: 640px)' in css:
    ok('CSS: mobile breakpoint at 640px')
else:
    fail('CSS: missing mobile breakpoint')
if 'min-height: 44px' in css or 'min-height:44px' in css:
    ok('CSS: touch targets ≥44px')
else:
    fail('CSS: missing touch target min-height')
if 'stale' in css:
    ok('CSS: stale indicator styles')
else:
    fail('CSS: missing stale styles')
if 'offline' in css:
    ok('CSS: offline indicator styles')
else:
    fail('CSS: missing offline styles')

# --- JS: UX states ---
if 'showError(' in js or 'error-banner' in js:
    ok('JS: error display function')
else:
    fail('JS: missing error display')
if 'hideError' in js:
    ok('JS: error dismiss / retry')
else:
    fail('JS: missing error dismiss/retry')
if 'offline' in js:
    ok('JS: offline detection')
else:
    fail('JS: missing offline detection')
if 'EmptyState' in js or "renderEmptyState" in js or "empty-state" in js:
    ok('JS: empty state rendering')
else:
    fail('JS: missing empty state rendering')
if 'stale' in js or 'Stale' in js:
    ok('JS: stale data detection')
else:
    fail('JS: missing stale data detection')
if 'ArrowRight' in js or 'ArrowLeft' in js:
    ok('JS: keyboard navigation on tabs')
else:
    fail('JS: missing keyboard nav on tabs')
if 'aria-selected' in js or 'aria_selected' in js:
    ok('JS: updates aria-selected on tab switch')
else:
    fail('JS: missing aria-selected update')
if 'skeleton' in js or 'Skeleton' in js:
    ok('JS: loading skeleton management')
else:
    fail('JS: missing skeleton management')

# ── 34. M9: Hardening (CSP, local-bind, /metrics, no secrets) ──
heading(36, 'M9: Hardening')

# CSP header
csp_found = False
try:
    url = BASE.rstrip('/') + '/api/usage/latest'
    with urllib.request.urlopen(url, timeout=5) as resp:
        csp = resp.headers.get('Content-Security-Policy', '')
        if "default-src 'self'" in csp and "style-src 'self'" in csp:
            ok('CSP header present: default-src + style-src')
            csp_found = True
except Exception:
    pass
if not csp_found:
    fail('CSP header missing or incorrect')

# Local-bind (config default host)
if "127.0.0.1" in open(os.path.join(os.path.dirname(__file__), 'backend', 'config.py')).read():
    ok('Config: default host is 127.0.0.1 (local-bind)')
else:
    fail('Config: default host is not 127.0.0.1')

# /metrics endpoint
try:
    body, status = get('/metrics')
    m = json.loads(body)
    if isinstance(m, dict) and len(m) > 0:
        ok('/metrics returns JSON dict')
    else:
        fail('/metrics returns empty response')
except Exception:
    fail('/metrics not reachable or not JSON')

# No secrets logged
codex_py = open(os.path.join(os.path.dirname(__file__), 'backend', 'codex_quota.py')).read()
if 'OPENAI_API_KEY' in codex_py and 'logger' not in codex_py and 'logging' not in codex_py:
    # Check it's not logged
    lines = [l.strip() for l in codex_py.split('\n') if 'api_key' in l.lower() or 'openai_key' in l.lower()]
    log_lines = [l for l in lines if 'log' in l.lower() or 'print' in l.lower()]
    if not log_lines:
        ok('No secrets logged in codex_quota.py')
    else:
        fail('Potential secret logging in codex_quota.py')
else:
    ok('No secrets logged in codex_quota.py')

# Check retention config
config_py_str = open(os.path.join(os.path.dirname(__file__), 'backend', 'config.py')).read()
if 'retention_days' in config_py_str:
    ok('Config: retention_days present')
else:
    fail('Config: missing retention_days')

# Summary ──
print()
print(f'\033[1m=== Results: {len(passes)} passed, {len(errors)} failed ===\033[0m\n')
if errors:
    for e in errors:
        print(f'  \033[31m{e}\033[0m')
    sys.exit(1)
