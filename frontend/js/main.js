import { state, HISTORY_STALE_MS, RANGE_LABELS } from './state.js';
import { formatNum, formatCost } from './format.js';
import { showError, hideError, setStatus, setRetryHandler } from './ui/banners.js';
import { showLoadingSkeleton, hideAllSkeletons } from './ui/skeleton.js';
import { renderOverview } from './ui/kpis.js';
import { renderModels, renderSortedModels, refreshModels } from './ui/table.js';
import { fetchLatest, fetchHistory, fetchQuota, fetchIntegrity } from './api.js';
import { computeOverviewFromHistory } from './derive.js';
import { renderHistoryChart, renderModelChart, charts } from './charts.js';
import { render as renderCycleStrip } from './ui/strip.js';

// Main refresh function - called by various event handlers
export async function refresh(force = false) {
    if (state.offline) return;
    hideError();
    // Step 1: fetch latest observations first so latestObservedCycleTs is known
    // before firing it off alongside the other concurrent fetches.
    const latestOk = await fetchLatest();
    const now = Date.now();
    const needHistory = !state.cachedHistory
        || !latestOk
        || state.latestObservedCycleTs == null
        || state.latestObservedCycleTs !== state.lastHistoryCycleTs
        || (now - state.lastHistoryFetchTime) > HISTORY_STALE_MS;
    const pending = [fetchQuota(force), fetchIntegrity()];
    if (needHistory) pending.push(fetchHistory());
    await Promise.all(pending);
    if (needHistory) {
        state.lastHistoryCycleTs = state.latestObservedCycleTs;
        state.lastHistoryFetchTime = now;
    }
    if (state.timeRange !== 'all' && state.cachedHistory) {
        const overview = computeOverviewFromHistory(state.cachedHistory, state.timeRange);
        if (overview) renderOverview(overview);
    }
    await refreshModels();
    state.lastFetchTime = Date.now();
    renderCycleStrip(state.cachedHistory);
    document.getElementById('last-updated').textContent =
        'updated ' + new Date().toLocaleTimeString();
    hideAllSkeletons();
}

// One orchestrated moment on source change: the main region cross-fades and
// settles. Restarting the animation needs a reflow between remove and add, or
// the class change coalesces and nothing plays. Skipped entirely under
// prefers-reduced-motion — the CSS also zeroes it, this just avoids the churn.
function playSourceSwitch() {
    const main = document.getElementById('panel-main');
    if (!main) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    main.classList.remove('source-switching');
    void main.offsetWidth;
    main.classList.add('source-switching');
}

document.addEventListener('DOMContentLoaded', async () => {
    setRetryHandler(refresh);
    // Try to restore time range from localStorage
    try {
        state.timeRange = localStorage.getItem('dashboard_timeRange') || 'all';
    } catch (e) {
        console.warn('localStorage is not accessible:', e);
    }

    // Restore time range active button state
    document.querySelectorAll('.range-btn').forEach(btn => {
        if (btn.dataset.range === state.timeRange) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Setup refresh button
    const refreshBtn = document.getElementById('refresh-btn');
    const refreshText = document.getElementById('refresh-text');
    if (refreshBtn) {
        let refreshTimeout;
        refreshBtn.addEventListener('click', async () => {
            if (refreshBtn.disabled || state.offline) return;
            refreshBtn.disabled = true;
            refreshBtn.classList.remove('success');
            refreshBtn.classList.add('loading');
            if (refreshText) refreshText.textContent = 'Refreshing...';

            const minWait = new Promise(resolve => setTimeout(resolve, 600));

            try {
                state.lastHistoryFetchTime = 0;
                await Promise.all([refresh(true), minWait]);
                setStatus('live', 'Live');
                refreshBtn.classList.remove('loading');
                refreshBtn.classList.add('success');
                if (refreshText) refreshText.textContent = 'Refreshed!';
            } catch (err) {
                refreshBtn.classList.remove('loading');
                if (refreshText) refreshText.textContent = 'Refresh';
                refreshBtn.disabled = false;
                return;
            }

            clearTimeout(refreshTimeout);
            refreshTimeout = setTimeout(() => {
                refreshBtn.classList.remove('success');
                if (refreshText) refreshText.textContent = 'Refresh';
                refreshBtn.disabled = false;
            }, 1200);
        });
    }

    // --- Offline detection ---
    window.addEventListener('online', () => {
        state.offline = false;
        setStatus('live', 'Live');
        refresh();
    });
    window.addEventListener('offline', () => {
        state.offline = true;
        setStatus('offline', 'Offline');
        showError('You are offline. Data will refresh when connection is restored.');
    });

    // --- Tab switching ---
    document.querySelectorAll('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');
            btn.focus();
            state.currentSource = btn.dataset.source;
            state.cachedHistory = null;
            state.cachedLatestOverview = null;
            hideError();
            showLoadingSkeleton();
            playSourceSwitch();
            refresh();
        });
        btn.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                const tabs = Array.from(document.querySelectorAll('.tab'));
                const idx = tabs.indexOf(btn);
                const next = tabs[(idx + 1) % tabs.length];
                next.focus();
                next.click();
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                const tabs = Array.from(document.querySelectorAll('.tab'));
                const idx = tabs.indexOf(btn);
                const prev = tabs[(idx - 1 + tabs.length) % tabs.length];
                prev.focus();
                prev.click();
            }
        });
    });

    // --- Time range buttons ---
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const newRange = btn.dataset.range;
            if (state.timeRange !== newRange) {
                state.timeRange = newRange;
                try {
                    localStorage.setItem('dashboard_timeRange', state.timeRange);
                } catch (e) {
                    console.warn('Failed to save to localStorage:', e);
                }
                state.cachedHistory = null;
                refresh();
            }
        });
    });

    // --- Mode toggle ---
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.mode = btn.dataset.mode;
            const isCombined = state.currentSource === 'combined';
            const historyValid = isCombined
                ? (state.cachedHistory && typeof state.cachedHistory === 'object' && !Array.isArray(state.cachedHistory))
                : Array.isArray(state.cachedHistory);
            if (historyValid) renderHistoryChart(state.cachedHistory);
        });
    });

    // --- Table sort ---
    // Screen readers announce sort state from aria-sort, not from the arrow
    // glyph, so it has to track state.sortColumn/sortDirection on every change.
    function syncAriaSort() {
        document.querySelectorAll('#models-table th.sortable').forEach(th => {
            if (th.dataset.sort === state.sortColumn) {
                th.setAttribute('aria-sort', state.sortDirection === 'asc' ? 'ascending' : 'descending');
            } else {
                th.setAttribute('aria-sort', 'none');
            }
        });
    }

    document.querySelectorAll('#models-table th.sortable').forEach(th => {
        // A clickable <th> is not focusable or operable by keyboard on its own.
        if (!th.hasAttribute('tabindex')) th.setAttribute('tabindex', '0');
        const activate = () => {
            const col = th.dataset.sort;
            if (state.sortColumn === col) {
                state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortColumn = col;
                state.sortDirection = (col === 'model_name') ? 'asc' : 'desc';
            }
            syncAriaSort();
            renderSortedModels();
        };
        th.addEventListener('click', activate);
        th.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
        });
    });
    syncAriaSort();

    // --- Initial load + auto-refresh every 60s ---
    if (state.offline) {
        setStatus('offline', 'Offline');
    }
    refresh();
    setInterval(() => {
        if (state.offline) return;
        if (document.visibilityState === 'hidden') return;
        const elapsed = (Date.now() - state.lastFetchTime) / 1000;
        if (elapsed > 120) {
            setStatus('stale', 'Stale');
        }
        refresh();
    }, 60_000);

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && !state.offline) {
            refresh();
        }
    });
});
