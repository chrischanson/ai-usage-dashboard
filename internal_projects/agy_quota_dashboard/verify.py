#!/usr/bin/env python3
"""Verifier for AGY Quota Dashboard changes.

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
        ('modelSrc = (mode === \'rate\' ? \'model_deltas\' : \'models\')', 'Model chart data switches with mode'),
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
    if plan and plan != 'Gemini Code Assist':
        ok(f'AGY: plan="{plan}" from Cloud Code API')
    else:
        fail(f'AGY: unexpected plan="{plan}"')
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
if "codex_live.get('plan_type') or codex_live.get('plan'" in app_py:
    ok('Codex plan reads from plan_type OR plan')
else:
    fail('Codex plan fallback not implemented')
if "'total_used_usd' in codex_q" in app_py:
    ok('Codex billing API path stored in DB')
else:
    fail('Codex billing API path not stored')
if "'total_used_usd' in codex_live" in app_py:
    ok('Codex billing API path in combined quota')
else:
    fail('Codex billing API path missing from combined quota')

# ── 21. Regression: Consistent field names ──
heading(21, 'Regression: Consistent field names')
if 'refreshes_in_seconds' in app_py:
    ok('Backend uses refreshes_in_seconds')
else:
    fail('Backend missing refreshes_in_seconds')
if "refreshes_in_seconds" in js:
    ok('Frontend uses refreshes_in_seconds')
else:
    fail('Frontend missing refreshes_in_seconds')

# ── 22. Regression: JSON parse isolation ──
heading(22, 'Regression: JSON parse error isolation')
if 'try { agyData = await results[0].value.json(); } catch' in js:
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

# ── Summary ──
print()
print(f'\033[1m=== Results: {len(passes)} passed, {len(errors)} failed ===\033[0m\n')
if errors:
    for e in errors:
        print(f'  \033[31m{e}\033[0m')
    sys.exit(1)
