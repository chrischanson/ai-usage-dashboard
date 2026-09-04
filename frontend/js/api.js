import { state } from './state.js';
import { showError, showIntegrityWarning, hideIntegrityWarning } from './ui/banners.js';
import { renderEmptyState } from './ui/skeleton.js';
import { renderOverview } from './ui/kpis.js';
import { renderQuota } from './ui/quota.js';
import { renderHistoryChart, charts } from './charts.js';
import { setCadence, setIntegrityWarnings } from './ui/strip.js';
import { getSourceNames, getSourceDisplayName } from './sources.js';

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
            const sourceNames = getSourceNames();
            
            // Newest poll cycle across all sources — used by refresh()
            // to decide whether the history series actually has new data.
            const cycleTss = sourceNames.map(name => (raw[name] || {}).cycle_ts).filter(v => v != null);
            state.latestObservedCycleTs = cycleTss.reduce((max, v) => (max == null || v > max) ? v : max, null);

            data = {
                sessions: 0,
                messages: 0,
                input_tokens: 0,
                output_tokens: 0,
                cache_read: 0,
                models: [],
                model_deltas: [],
                _modelDeltas: []
            };

            sourceNames.forEach(name => {
                const srcData = raw[name] || {};
                data.sessions += (srcData.sessions || 0);
                data.messages += (srcData.messages || 0);
                data.input_tokens += (srcData.input_tokens || 0);
                data.output_tokens += (srcData.output_tokens || 0);
                data.cache_read += (srcData.cache_read || 0);

                const modelsCumulative = (srcData.models || []).map(function(m) { return Object.assign({}, m, { source: name }); });
                data.models.push(...modelsCumulative);

                const deltas = (srcData.model_deltas || []).map(function(m) { return Object.assign({}, m, { source: name }); });
                data._modelDeltas.push(...deltas);
            });

            data.models.sort(function(a, b) {
                return ((b.input_tokens || 0) + (b.output_tokens || 0)) - ((a.input_tokens || 0) + (a.output_tokens || 0));
            });

            data._modelDeltas.sort(function(a, b) {
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
            const sourceNames = getSourceNames();
            const results = await Promise.allSettled(
                sourceNames.map(name => fetch(`/api/usage/${name}/history` + rangeParam))
            );

            const parsedResults = await Promise.all(results.map(async (res) => {
                if (res.status === 'fulfilled' && res.value.ok) {
                    try { return await res.value.json(); } catch (_) {}
                }
                return [];
            }));

            const historyData = {};
            sourceNames.forEach((name, i) => {
                historyData[name] = parsedResults[i] || [];
            });

            if (sourceNames.length > 0) {
                const sets = sourceNames.map(name => new Set(historyData[name].map(d => d.timestamp)));
                const firstSet = sets[0];
                let latestTs = null;
                for (const ts of firstSet) {
                    if (sets.every(set => set.has(ts))) {
                        if (latestTs === null || ts > latestTs) {
                            latestTs = ts;
                        }
                    }
                }

                if (latestTs !== null) {
                    state.latestCompleteTimestamp = latestTs;
                    sourceNames.forEach(name => {
                        historyData[name] = historyData[name].filter(d => d.timestamp <= latestTs);
                    });
                } else {
                    sourceNames.forEach(name => {
                        historyData[name] = [];
                    });
                }
            }

            state.cachedHistory = historyData;
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
        const titleEl = document.getElementById('quota-title');
        if (titleEl) {
            if (state.currentSource === 'combined') {
                titleEl.textContent = 'Quota Limits';
            } else {
                titleEl.textContent = `${getSourceDisplayName(state.currentSource)} Quota Limits`;
            }
        }
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        renderQuota(data, state.currentSource);
    } catch (e) {
        console.error('fetchQuota error:', e);
        const container = document.getElementById('quota-cards');
        if (container) {
            // The request itself failed, so there is no fresher data to show.
            // Cards already on screen stay -- they are the last known good
            // reading, and blanking them loses information the user had.
            const hasCards = container.querySelector('.quota-group');
            if (hasCards) {
                let note = container.querySelector('.quota-fetch-error');
                if (!note) {
                    note = document.createElement('p');
                    note.className = 'quota-note quota-fetch-error';
                    note.setAttribute('role', 'status');
                    container.prepend(note);
                }
                note.textContent = 'Could not refresh — showing the last loaded values.';
            } else {
                container.innerHTML = '<div class="empty-state"><p>Failed to retrieve quota data.</p></div>';
            }
        }
    }
}
