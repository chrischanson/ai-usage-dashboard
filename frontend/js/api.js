import { state } from './state.js';
import { showError, showIntegrityWarning, hideIntegrityWarning } from './ui/banners.js';
import { renderEmptyState } from './ui/skeleton.js';
import { renderOverview } from './ui/kpis.js';
import { renderQuota } from './ui/quota.js';
import { renderHistoryChart, charts } from './charts.js';
import { setCadence, setIntegrityWarnings } from './ui/strip.js';

export async function fetchIntegrity() {
    try {
        const resp = await fetch('/metrics');
        if (!resp.ok) return;
        const data = await resp.json();
        const integrity = data && data.integrity;
        if (integrity && integrity.ok === false) {
            showIntegrityWarning(integrity.warnings || []);
            setIntegrityWarnings(integrity.warnings || []);
        } else {
            hideIntegrityWarning();
            setIntegrityWarnings([]);
        }
    } catch (e) {
        // Integrity checks are best-effort; a failed fetch here shouldn't
        // block or clutter the main error banner used for usage data.
    }
}

export async function fetchLatest() {
    try {
        let data;
        const deltasParam = state.mode === 'rate' ? '?deltas=true' : '';
        if (state.currentSource === 'combined') {
            const resp = await fetch('/api/usage/latest' + deltasParam);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const raw = await resp.json();
            setCadence(raw._meta, null);
            const agy = raw.agy || {};
            const opencode = raw.opencode || {};
            const codex = raw.codex || {};
            const claude = raw.claude || {};

            // Newest poll cycle across all four sources — used by refresh()
            // to decide whether the history series actually has new data.
            state.latestObservedCycleTs = [agy.cycle_ts, opencode.cycle_ts, codex.cycle_ts, claude.cycle_ts]
                .filter(v => v != null)
                .reduce((max, v) => (max == null || v > max) ? v : max, null);

            data = {
                sessions: (agy.sessions || 0) + (opencode.sessions || 0) + (codex.sessions || 0) + (claude.sessions || 0),
                messages: (agy.messages || 0) + (opencode.messages || 0) + (codex.messages || 0) + (claude.messages || 0),
                input_tokens: (agy.input_tokens || 0) + (opencode.input_tokens || 0) + (codex.input_tokens || 0) + (claude.input_tokens || 0),
                output_tokens: (agy.output_tokens || 0) + (opencode.output_tokens || 0) + (codex.output_tokens || 0) + (claude.output_tokens || 0),
                cache_read: (agy.cache_read || 0) + (opencode.cache_read || 0) + (codex.cache_read || 0) + (claude.cache_read || 0),
                models: [],
                model_deltas: [],
            };

            const agyModelsCumulative = (agy.models || []).map(function(m) { return Object.assign({}, m, { source: 'agy' }); });
            const opencodeModelsCumulative = (opencode.models || []).map(function(m) { return Object.assign({}, m, { source: 'opencode' }); });
            const codexModelsCumulative = (codex.models || []).map(function(m) { return Object.assign({}, m, { source: 'codex' }); });
            const claudeModelsCumulative = (claude.models || []).map(function(m) { return Object.assign({}, m, { source: 'claude' }); });
            data.models = [...agyModelsCumulative, ...opencodeModelsCumulative, ...codexModelsCumulative, ...claudeModelsCumulative].sort(function(a, b) {
                return ((b.input_tokens || 0) + (b.output_tokens || 0)) - ((a.input_tokens || 0) + (a.output_tokens || 0));
            });

            const agyDeltas = (agy.model_deltas || []).map(function(m) { return Object.assign({}, m, { source: 'agy' }); });
            const opencodeDeltas = (opencode.model_deltas || []).map(function(m) { return Object.assign({}, m, { source: 'opencode' }); });
            const codexDeltas = (codex.model_deltas || []).map(function(m) { return Object.assign({}, m, { source: 'codex' }); });
            const claudeDeltas = (claude.model_deltas || []).map(function(m) { return Object.assign({}, m, { source: 'claude' }); });
            data._modelDeltas = [...agyDeltas, ...opencodeDeltas, ...codexDeltas, ...claudeDeltas].sort(function(a, b) {
                return ((b.input_tokens || 0) + (b.output_tokens || 0)) - ((a.input_tokens || 0) + (a.output_tokens || 0));
            });
        } else {
            const resp = await fetch(`/api/usage/${state.currentSource}/latest` + deltasParam);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const rawSource = await resp.json();
            setCadence(rawSource._meta, null);
            data = rawSource[state.currentSource] || rawSource;
            data._modelDeltas = data.model_deltas || [];
            data.models = data.models || [];
            state.latestObservedCycleTs = (data && data.cycle_ts != null) ? data.cycle_ts : null;
        }

        if (!data || Object.keys(data).length === 0) {
            state.cachedLatestOverview = null;
            renderEmptyState('overview');
            if (charts.modelChartInstance) {
                charts.modelChartInstance.destroy();
                charts.modelChartInstance = null;
            }
            return true;
        }
        state.cachedLatestOverview = data;
        renderOverview(data);
        return true;
    } catch (e) {
        console.error('fetchLatest error:', e);
        if (!state.cachedLatestOverview) {
            renderEmptyState('overview');
        }
        showError('Failed to load latest usage data. ' + (e.message || ''));
        // Unknown cycle_ts on failure — refresh() must treat this as "may
        // have changed" and fetch history anyway rather than freeze the charts.
        return false;
    }
}

export async function fetchHistory() {
    try {
        const rangeParam = '?range=' + state.timeRange;
        if (state.currentSource === 'combined') {
            const results = await Promise.allSettled([
                fetch('/api/usage/agy/history' + rangeParam),
                fetch('/api/usage/opencode/history' + rangeParam),
                fetch('/api/usage/codex/history' + rangeParam),
                fetch('/api/usage/claude/history' + rangeParam)
            ]);
            let agyData = [], opencodeData = [], codexData = [], claudeData = [];
            if (results[0].status === 'fulfilled') {
                try { if (results[0].value.ok) agyData = await results[0].value.json(); } catch (_) {}
            }
            if (results[1].status === 'fulfilled') {
                try { if (results[1].value.ok) opencodeData = await results[1].value.json(); } catch (_) {}
            }
            if (results[2].status === 'fulfilled') {
                try { if (results[2].value.ok) codexData = await results[2].value.json(); } catch (_) {}
            }
            if (results[3].status === 'fulfilled') {
                try { if (results[3].value.ok) claudeData = await results[3].value.json(); } catch (_) {}
            }

            let agy = agyData;
            let opencode = opencodeData;
            let codex = codexData;
            let claude = claudeData;

            const agySet = new Set(agy.map(d => d.timestamp));
            const opencodeSet = new Set(opencode.map(d => d.timestamp));
            const codexSet = new Set(codex.map(d => d.timestamp));
            const claudeSet = new Set(claude.map(d => d.timestamp));

            let latestTs = null;
            for (const ts of agySet) {
                if (opencodeSet.has(ts) && codexSet.has(ts) && claudeSet.has(ts)) {
                    if (latestTs === null || ts > latestTs) {
                        latestTs = ts;
                    }
                }
            }

            if (latestTs !== null) {
                state.latestCompleteTimestamp = latestTs;
                agy = agy.filter(d => d.timestamp <= latestTs);
                opencode = opencode.filter(d => d.timestamp <= latestTs);
                codex = codex.filter(d => d.timestamp <= latestTs);
                claude = claude.filter(d => d.timestamp <= latestTs);
            } else {
                agy = [];
                opencode = [];
                codex = [];
                claude = [];
            }

            state.cachedHistory = { agy, opencode, codex, claude };
            renderHistoryChart(state.cachedHistory);
        } else {
            const resp = await fetch(`/api/usage/${state.currentSource}/history` + rangeParam);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            let data = await resp.json();
            // Note: latestCompleteTimestamp is a combined-view concept (the
            // last cycle where every source reported, so the summed total
            // isn't understated by a lagging source) and must not be
            // applied here — this is a single source's own chart, so it
            // should show all of that source's own data regardless of
            // whether any other source reported at the same instant. A
            // stalled source used to freeze every other source's view at
            // its last-good timestamp until it recovered.
            state.cachedHistory = (data && data.length > 0) ? data : [];
            renderHistoryChart(state.cachedHistory);
        }
    } catch (e) {
        console.error('fetchHistory error:', e);
    }
}

export async function fetchQuota(force = false) {
    try {
        let url = '/api/quota/latest';
        if (state.currentSource !== 'combined') {
            url = `/api/quota/${state.currentSource}/latest`;
        }
        if (force) {
            url += (url.includes('?') ? '&' : '?') + 'force=true';
        }
        const titleMap = {
            combined: 'Quota Limits',
            agy: 'AGY Quota Limits',
            opencode: 'OpenCode CLI Spending',
            codex: 'Codex Usage Limits',
            claude: 'Claude Usage Limits',
        };
        const titleEl = document.getElementById('quota-title');
        if (titleEl) titleEl.textContent = titleMap[state.currentSource] || 'Quota Limits';
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        renderQuota(data, state.currentSource);
    } catch (e) {
        console.error('fetchQuota error:', e);
        const container = document.getElementById('quota-cards');
        if (container) {
            container.innerHTML = '<div class="empty-state"><p>Failed to retrieve quota data.</p></div>';
        }
    }
}
