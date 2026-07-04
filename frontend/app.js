document.addEventListener('DOMContentLoaded', () => {
    let historyChartInstance = null;
    let modelChartInstance = null;
    let currentSource = 'combined';
    let timeRange = 'all';
    let mode = 'total';
    let cachedHistory = null;
    let cachedLatestOverview = null;
    let lastFetchTime = 0;
    let offline = !navigator.onLine;
    let sortColumn = 'total';
    let sortDirection = 'desc';
    let cachedModelData = null;
    let latestCompleteTimestamp = null;

    // Clamp values interpolated into inline style="width: N%" so a malformed
    // upstream reading can't produce a non-numeric or out-of-range style value.
    function clampPct(value) {
        const n = Number(value);
        if (!Number.isFinite(n)) return 0;
        return Math.max(0, Math.min(100, n));
    }

    const RANGE_LABELS = {
        '1h': ' (Last Hour)',
        '6h': ' (Last 6 Hours)',
        '1d': ' (Last 24 Hours)',
        '1w': ' (Last Week)',
        '1m': ' (Last Month)',
        '3m': ' (Last 3 Months)',
        'all': ' (All Time)'
    };

    if (typeof Chart !== 'undefined') {
        Chart.defaults.color = '#8a9fc8';
        Chart.defaults.font.family = "'Inter', sans-serif";
    }

    const canvas = document.getElementById('historyChart');
    if (canvas) {
        canvas.addEventListener('dblclick', () => {
            if (historyChartInstance && typeof historyChartInstance.resetZoom === 'function') {
                historyChartInstance.resetZoom();
            }
        });
    }

    // --- Source colors ---
    const COLORS = {
        agy: {
            accent: '#9b6dff',
            line: '#9b6dff',
            lineFill: 'rgba(155, 109, 255, 0.12)',
            outLine: '#4f8aff',
            outFill: 'rgba(79, 138, 255, 0.08)',
            donut: ['#9b6dff', '#4f8aff', '#10c48a', '#f59e0b', '#ec4899', '#f97316'],
        },
        opencode: {
            accent: '#4f8aff',
            line: '#4f8aff',
            lineFill: 'rgba(79, 138, 255, 0.12)',
            outLine: '#10c48a',
            outFill: 'rgba(16, 196, 138, 0.08)',
            donut: ['#4f8aff', '#10c48a', '#f59e0b', '#9b6dff', '#ec4899', '#f97316'],
        },
        codex: {
            accent: '#10b981',
            line: '#10b981',
            lineFill: 'rgba(16, 185, 129, 0.12)',
            outLine: '#34d399',
            outFill: 'rgba(52, 211, 153, 0.08)',
            donut: ['#10b981', '#34d399', '#f59e0b', '#9b6dff', '#ec4899', '#f97316'],
        },
        claude: {
            accent: '#d4a574',
            line: '#d4a574',
            lineFill: 'rgba(212, 165, 116, 0.12)',
            outLine: '#e8c49a',
            outFill: 'rgba(232, 196, 154, 0.08)',
            donut: ['#d4a574', '#e8c49a', '#f59e0b', '#9b6dff', '#ec4899', '#f97316'],
        },
        combined: {
            accent: '#10c48a',
            donut: ['#9b6dff', '#4f8aff', '#10c48a', '#d4a574', '#f59e0b', '#ec4899', '#f97316'],
        },
    };

    // --- Helpers ---
    function formatNum(n) {
        if (n == null) return '--';
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
        if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
        return Math.round(n).toLocaleString();
    }

    function formatCost(n) {
        if (n == null || n === 0) return '--';
        if (n < 0.01) return '<$0.01';
        return '$' + n.toFixed(2);
    }

    function setCard(id, val) {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove('skeleton', 'skeleton-text');
            el.textContent = val;
        }
    }

    function showLoadingSkeleton() {
        document.querySelectorAll('.skeleton').forEach(el => {
            el.style.display = '';
        });
    }

    function hideAllSkeletons() {
        document.querySelectorAll('.skeleton').forEach(el => {
            el.style.display = 'none';
        });
    }

    // --- Error banner ---
    const errorBanner = document.getElementById('error-banner');
    const errorMsg = document.getElementById('error-message');
    const retryBtn = document.getElementById('retry-btn');
    const dismissBtn = document.getElementById('dismiss-btn');

    function showError(msg) {
        if (!errorBanner || !errorMsg) return;
        errorMsg.textContent = msg;
        errorBanner.hidden = false;
    }

    function hideError() {
        if (!errorBanner) return;
        errorBanner.hidden = true;
    }

    if (retryBtn) {
        retryBtn.addEventListener('click', () => {
            hideError();
            refresh();
        });
    }
    if (dismissBtn) {
        dismissBtn.addEventListener('click', () => {
            hideError();
        });
    }

    // --- Status indicator ---
    const statusText = document.getElementById('status-text');
    const statusDot = document.querySelector('.dot');
    const statusIndicator = document.getElementById('status-indicator');

    function setStatus(type, text) {
        if (!statusText || !statusDot || !statusIndicator) return;
        statusText.textContent = text || 'Live';
        statusText.classList.remove('stale', 'offline');
        statusDot.classList.remove('stale', 'offline');
        statusIndicator.classList.remove('offline');
        if (type === 'stale') {
            statusText.classList.add('stale');
            statusDot.classList.add('stale');
        } else if (type === 'offline') {
            statusText.classList.add('offline');
            statusDot.classList.add('offline');
            statusIndicator.classList.add('offline');
        }
    }

    // --- Offline detection ---
    window.addEventListener('online', () => {
        offline = false;
        setStatus('live', 'Live');
        refresh();
    });
    window.addEventListener('offline', () => {
        offline = true;
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
            currentSource = btn.dataset.source;
            cachedHistory = null;
            cachedLatestOverview = null;
            hideError();
            showLoadingSkeleton();
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
            timeRange = btn.dataset.range;
            if (cachedHistory) {
                const isCombined = currentSource === 'combined';
                const historyValid = isCombined
                    ? (typeof cachedHistory === 'object' && !Array.isArray(cachedHistory))
                    : Array.isArray(cachedHistory);
                if (!historyValid) return;
                const overview = computeOverviewFromHistory(cachedHistory, timeRange);
                if (overview) {
                    renderOverview(overview);
                    const label = document.getElementById('time-range-label');
                    if (label) label.textContent = RANGE_LABELS[timeRange] || '';
                } else if (cachedLatestOverview) {
                    renderOverview(cachedLatestOverview);
                    const label = document.getElementById('time-range-label');
                    if (label) label.textContent = '';
                }
                renderHistoryChart(cachedHistory);
                refreshModels();
            }
        });
    });

    // --- Mode toggle ---
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            mode = btn.dataset.mode;
            const isCombined = currentSource === 'combined';
            const historyValid = isCombined
                ? (cachedHistory && typeof cachedHistory === 'object' && !Array.isArray(cachedHistory))
                : Array.isArray(cachedHistory);
            if (historyValid) renderHistoryChart(cachedHistory);
        });
    });

    // --- Table sort ---
    document.querySelectorAll('#models-table th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (sortColumn === col) {
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                sortColumn = col;
                sortDirection = (col === 'model_name') ? 'asc' : 'desc';
            }
            renderSortedModels();
        });
    });

    // --- Fetch & render ---
    async function refresh() {
        if (offline) return;
        hideError();
        await Promise.all([fetchLatest(), fetchHistory(), fetchQuota()]);
        if (timeRange !== 'all' && cachedHistory) {
            const overview = computeOverviewFromHistory(cachedHistory, timeRange);
            if (overview) renderOverview(overview);
        }
        refreshModels();
        lastFetchTime = Date.now();
        document.getElementById('last-updated').textContent =
            'Last updated: ' + new Date().toLocaleTimeString();
        hideAllSkeletons();
    }

    async function fetchLatest() {
        try {
            let data;
            const deltasParam = mode === 'rate' ? '?deltas=true' : '';
            if (currentSource === 'combined') {
                const resp = await fetch('/api/usage/latest' + deltasParam);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const raw = await resp.json();
                const agy = raw.agy || {};
                const opencode = raw.opencode || {};
                const codex = raw.codex || {};
                const claude = raw.claude || {};

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
                const resp = await fetch(`/api/usage/${currentSource}/latest` + deltasParam);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                data = await resp.json();
                data._modelDeltas = data.model_deltas || [];
                data.models = data.models || [];
            }

            if (!data || Object.keys(data).length === 0) {
                cachedLatestOverview = null;
                renderEmptyState('overview');
                if (modelChartInstance) { modelChartInstance.destroy(); modelChartInstance = null; }
                return;
            }
            cachedLatestOverview = data;
            renderOverview(data);
        } catch (e) {
            console.error('fetchLatest error:', e);
            if (!cachedLatestOverview) {
                renderEmptyState('overview');
            }
            showError('Failed to load latest usage data. ' + (e.message || ''));
        }
    }

    async function fetchHistory() {
        try {
            if (currentSource === 'combined') {
                const results = await Promise.allSettled([
                    fetch('/api/usage/agy/history'),
                    fetch('/api/usage/opencode/history'),
                    fetch('/api/usage/codex/history'),
                    fetch('/api/usage/claude/history')
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
                
                while (true) {
                    const allTimes = Array.from(new Set([
                        ...agy.map(d => d.timestamp),
                        ...opencode.map(d => d.timestamp),
                        ...codex.map(d => d.timestamp),
                        ...claude.map(d => d.timestamp)
                    ])).sort();
                    
                    if (allTimes.length === 0) break;
                    
                    const latestTs = allTimes[allTimes.length - 1];
                    const hasAgy = agy.some(d => d.timestamp === latestTs);
                    const hasOpencode = opencode.some(d => d.timestamp === latestTs);
                    const hasCodex = codex.some(d => d.timestamp === latestTs);
                    const hasClaude = claude.some(d => d.timestamp === latestTs);
                    
                    if (!(hasAgy && hasOpencode && hasCodex && hasClaude)) {
                        agy = agy.filter(d => d.timestamp !== latestTs);
                        opencode = opencode.filter(d => d.timestamp !== latestTs);
                        codex = codex.filter(d => d.timestamp !== latestTs);
                        claude = claude.filter(d => d.timestamp !== latestTs);
                    } else {
                        latestCompleteTimestamp = latestTs;
                        break;
                    }
                }
                
                cachedHistory = { agy, opencode, codex, claude };
                renderHistoryChart(cachedHistory);
            } else {
                const resp = await fetch(`/api/usage/${currentSource}/history`);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                let data = await resp.json();
                if (data && data.length > 0) {
                    if (latestCompleteTimestamp) {
                        data = data.filter(d => parseTs(d.timestamp) <= parseTs(latestCompleteTimestamp));
                    }
                    cachedHistory = data;
                } else {
                    cachedHistory = [];
                }
                renderHistoryChart(cachedHistory);
            }
        } catch (e) {
            console.error('fetchHistory error:', e);
        }
    }

    function renderEmptyState(target) {
        if (target === 'overview') {
            setCard('total-sessions', '--');
            setCard('total-messages', '--');
            setCard('input-tokens', 'No data available');
            setCard('output-tokens', '--');
            setCard('cache-reads', '--');
        } else if (target === 'models') {
            const tbody = document.getElementById('models-tbody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><div class="empty-state-icon">&#128202;</div><p>No data collected yet. Polling runs every 10 minutes.</p></td></tr>';
            }
        }
    }

    function renderOverview(data) {
        setCard('total-sessions', formatNum(data.sessions));
        setCard('total-messages', formatNum(data.messages));
        setCard('input-tokens', formatNum(data.input_tokens));
        setCard('output-tokens', formatNum(data.output_tokens));
        setCard('cache-reads', formatNum(data.cache_read));
    }

    function renderModels(models) {
        const tbody = document.getElementById('models-tbody');
        if (!tbody) return;
        if (!models || !models.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><div class="empty-state-icon">&#128202;</div><p>No model usage data available.</p></td></tr>';
            return;
        }

        const palette = COLORS[currentSource].donut;
        const grandTotal = models.reduce((sum, m) => sum + (m.input_tokens || 0) + (m.output_tokens || 0), 0);

        const rows = models.map((m, i) => {
            const input = m.input_tokens || 0;
            const output = m.output_tokens || 0;
            const total = input + output;
            const pct = grandTotal > 0 ? (total / grandTotal * 100) : 0;
            const cost = m.cost;
            const color = palette[i % palette.length];
            const name = m.model_name.split('/').pop();
            const badgeHtml = m.source ? `<span class="badge badge-${m.source}">${escapeHtml(m.source)}</span>` : '';
            return {
                model_name: m.model_name,
                displayName: name,
                badge: badgeHtml,
                color: color,
                input_tokens: input,
                output_tokens: output,
                total: total,
                pct: pct,
                cost: cost,
                messages: m.messages || 0,
            };
        });

        cachedModelData = rows;
        renderSortedModels();
    }

    function renderSortedModels() {
        const tbody = document.getElementById('models-tbody');
        if (!tbody || !cachedModelData) return;

        const sorted = [...cachedModelData].sort((a, b) => {
            let av, bv;
            if (sortColumn === 'model_name') {
                av = a.model_name.toLowerCase();
                bv = b.model_name.toLowerCase();
                if (av < bv) return sortDirection === 'asc' ? -1 : 1;
                if (av > bv) return sortDirection === 'asc' ? 1 : -1;
                return 0;
            }
            av = a[sortColumn] || 0;
            bv = b[sortColumn] || 0;
            return sortDirection === 'asc' ? av - bv : bv - av;
        });

        tbody.innerHTML = sorted.map(m => {
            const costDisplay = formatCost(m.cost);
            const costClass = (m.cost == null || m.cost === 0) ? 'model-cost muted' : 'model-cost';
            return `<tr>
                <td><div class="model-name"><span class="model-color-dot" style="background:${m.color}"></span>${escapeHtml(m.model_name)}${m.badge}</div></td>
                <td>${formatNum(m.input_tokens)}</td>
                <td>${formatNum(m.output_tokens)}</td>
                <td>${formatNum(m.total)}</td>
                <td>${m.pct.toFixed(1)}%</td>
                <td class="${costClass}">${costDisplay}</td>
            </tr>`;
        }).join('');

        document.querySelectorAll('#models-table th.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
            if (th.dataset.sort === sortColumn) {
                th.classList.add(sortDirection === 'asc' ? 'sort-asc' : 'sort-desc');
            }
        });
    }

    function renderModelChart(models) {
        if (typeof Chart === 'undefined') {
            console.warn('Chart.js is not loaded. Skipping model chart rendering.');
            return;
        }
        const ctx = document.getElementById('modelChart').getContext('2d');
        const palette = COLORS[currentSource].donut;
        const labels = models.map(m => {
            const name = m.model_name.split('/').pop();
            return m.source ? `${name} (${m.source})` : name;
        });
        const data = models.map(m => Math.max(0, (m.input_tokens || 0) + (m.output_tokens || 0)));

        if (modelChartInstance) modelChartInstance.destroy();

        const chartTitle = 'Model Distribution';

        modelChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: palette,
                    borderWidth: 0,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        align: 'start',
                        labels: { padding: 12, font: { size: 11 } },
                    },
                    title: {
                        display: true,
                        text: chartTitle,
                        color: '#8a9fc8',
                        font: { size: 10, weight: '600' },
                        padding: { bottom: 8 },
                    },
                },
            },
        });
    }

    function filterByTimeRange(data, range) {
        if (!Array.isArray(data) || range === 'all' || !data.length) return data;
        const timestamps = data.map(d => parseTs(d.timestamp).getTime());
        const dataEnd = Math.max(...timestamps);
        const ms = {
            '1h': 3600000, '6h': 21600000,
            '1d': 86400000, '1w': 604800000, '1m': 2592000000, '3m': 7776000000
        }[range] || 86400000;
        const cutoff = new Date(dataEnd - ms);
        return data.filter(d => parseTs(d.timestamp) >= cutoff);
    }

    function computeOverviewFromHistory(history, range) {
        if (range === 'all' || !history) return null;
        function sourceDelta(data) {
            if (!data || data.length < 2) return null;
            const filtered = filterByTimeRange(data, range);
            if (filtered.length < 2) return null;
            const first = filtered[0];
            const last = filtered[filtered.length - 1];
            return {
                sessions: Math.max(0, (last.sessions || 0) - (first.sessions || 0)),
                messages: Math.max(0, (last.messages || 0) - (first.messages || 0)),
                input_tokens: Math.max(0, (last.input_tokens || 0) - (first.input_tokens || 0)),
                output_tokens: Math.max(0, (last.output_tokens || 0) - (first.output_tokens || 0)),
                cache_read: Math.max(0, (last.cache_read || 0) - (first.cache_read || 0)),
            };
        }
        if (currentSource === 'combined') {
            const agy = sourceDelta(history.agy);
            const opencode = sourceDelta(history.opencode);
            const codex = sourceDelta(history.codex);
            const claude = sourceDelta(history.claude);
            return {
                sessions: (agy?.sessions || 0) + (opencode?.sessions || 0) + (codex?.sessions || 0) + (claude?.sessions || 0),
                messages: (agy?.messages || 0) + (opencode?.messages || 0) + (codex?.messages || 0) + (claude?.messages || 0),
                input_tokens: (agy?.input_tokens || 0) + (opencode?.input_tokens || 0) + (codex?.input_tokens || 0) + (claude?.input_tokens || 0),
                output_tokens: (agy?.output_tokens || 0) + (opencode?.output_tokens || 0) + (codex?.output_tokens || 0) + (claude?.output_tokens || 0),
                cache_read: (agy?.cache_read || 0) + (opencode?.cache_read || 0) + (codex?.cache_read || 0) + (claude?.cache_read || 0),
            };
        }
        return sourceDelta(history) || null;
    }

    function computeModelsFromHistory(history, range) {
        if (range === 'all' || !history) return null;
        function sourceModels(data) {
            if (!data || data.length < 2) return null;
            const filtered = filterByTimeRange(data, range);
            if (filtered.length < 2) return null;
            const first = filtered[0];
            const last = filtered[filtered.length - 1];
            const firstModels = {};
            (first.models || []).forEach(function(m) { firstModels[m.model_name] = m; });
            const deltas = [];
            (last.models || []).forEach(function(m) {
                const prev = firstModels[m.model_name] || {};
                const dm = {
                    model_name: m.model_name,
                    messages: Math.max(0, (m.messages || 0) - (prev.messages || 0)),
                    input_tokens: Math.max(0, (m.input_tokens || 0) - (prev.input_tokens || 0)),
                    output_tokens: Math.max(0, (m.output_tokens || 0) - (prev.output_tokens || 0)),
                };
                if (dm.messages > 0 || dm.input_tokens > 0 || dm.output_tokens > 0) {
                    deltas.push(dm);
                }
            });
            return deltas.length > 0 ? deltas : null;
        }
        if (currentSource === 'combined') {
            const agy = sourceModels(history.agy);
            const opencode = sourceModels(history.opencode);
            const codex = sourceModels(history.codex);
            const claude = sourceModels(history.claude);
            const combined = [];
            (agy || []).forEach(function(m) { combined.push(Object.assign({}, m, { source: 'agy' })); });
            (opencode || []).forEach(function(m) { combined.push(Object.assign({}, m, { source: 'opencode' })); });
            (codex || []).forEach(function(m) { combined.push(Object.assign({}, m, { source: 'codex' })); });
            (claude || []).forEach(function(m) { combined.push(Object.assign({}, m, { source: 'claude' })); });
            return combined.sort(function(a, b) {
                return ((b.input_tokens || 0) + (b.output_tokens || 0)) - ((a.input_tokens || 0) + (a.output_tokens || 0));
            });
        }
        return sourceModels(history) || [];
    }

    function refreshModels() {
        if (timeRange === 'all') {
            if (cachedLatestOverview) {
                renderModels(cachedLatestOverview.models || []);
                renderModelChart(cachedLatestOverview.models || []);
            } else {
                renderEmptyState('models');
                if (modelChartInstance) { modelChartInstance.destroy(); modelChartInstance = null; }
            }
        } else if (cachedHistory) {
            const isCombined = currentSource === 'combined';
            const historyValid = isCombined
                ? (typeof cachedHistory === 'object' && !Array.isArray(cachedHistory))
                : Array.isArray(cachedHistory);
            if (historyValid) {
                const models = computeModelsFromHistory(cachedHistory, timeRange);
                if (models && models.length > 0) {
                    renderModels(models);
                    renderModelChart(models);
                } else {
                    renderEmptyState('models');
                    if (modelChartInstance) { modelChartInstance.destroy(); modelChartInstance = null; }
                }
            }
        }
    }

    function parseTs(ts) {
        if (!ts) return null;
        const d = new Date(ts.replace(' ', 'T') + 'Z');
        return isNaN(d) ? null : d;
    }

    function formatLabel(ts) {
        const dt = parseTs(ts);
        if (!dt) return ts;
        const isMobile = window.innerWidth <= 640;
        if (isMobile) {
            return dt.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
        }
        return dt.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function renderHistoryChart(history) {
        if (typeof Chart === 'undefined') {
            console.warn('Chart.js is not loaded. Skipping history chart rendering.');
            return;
        }
        const ctx = document.getElementById('historyChart').getContext('2d');
        let datasets = [];
        let labels = [];
        const isTotal = mode === 'total';
        let unitLabel = isTotal ? 'Tokens' : '\u0394 tokens';

        if (currentSource === 'combined') {
            const agyFull = history.agy || [];
            const opencodeFull = history.opencode || [];
            const codexFull = history.codex || [];
            const claudeFull = history.claude || [];

            // The API serves cumulative-since-first-observation totals in
            // input_tokens/output_tokens and per-cycle increments in
            // delta_input_tokens/delta_output_tokens (derived in db.py from
            // the raw stored observations) — plot them as-is.
            let agy = filterByTimeRange(agyFull, timeRange);
            let opencode = filterByTimeRange(opencodeFull, timeRange);
            let codex = filterByTimeRange(codexFull, timeRange);
            let claude = filterByTimeRange(claudeFull, timeRange);

            const allTimes = Array.from(new Set([
                ...agy.map(d => d.timestamp),
                ...opencode.map(d => d.timestamp),
                ...codex.map(d => d.timestamp),
                ...claude.map(d => d.timestamp)
            ])).sort();

            labels = allTimes.map(formatLabel);

            // Forward-fill: for each unified timestamp, carry forward the last known
            // value from each source so gaps don't cause dips in stacked charts.
            const MS_TOLERANCE = 30 * 60 * 1000; // 30 minutes
            function buildFilledLookup(data) {
                const lookup = new Map();
                let lastEntry = null;
                let dataIdx = 0;
                for (const ts of allTimes) {
                    const t = parseTs(ts).getTime();
                    while (dataIdx < data.length) {
                        const dt = parseTs(data[dataIdx].timestamp);
                        if (!dt) { dataIdx++; continue; }
                        if (dt.getTime() <= t) {
                            lastEntry = data[dataIdx];
                            dataIdx++;
                        } else {
                            break;
                        }
                    }
                    // Only use if within tolerance of a real data point
                    if (lastEntry) {
                        const lastTs = parseTs(lastEntry.timestamp);
                        if (lastTs && Math.abs(lastTs.getTime() - t) <= MS_TOLERANCE) {
                            lookup.set(ts, lastEntry);
                        }
                    }
                }
                return lookup;
            }

            const agyLookup = buildFilledLookup(agy);
            const opencodeLookup = buildFilledLookup(opencode);
            const codexLookup = buildFilledLookup(codex);
            const claudeLookup = buildFilledLookup(claude);

            const mapFromLookup = (lookup, key) => {
                return allTimes.map(ts => {
                    const found = lookup.get(ts);
                    return found ? found[key] : 0;
                });
            };

            // Rate mode plots the backend-served per-cycle deltas
            // (delta_input_tokens / delta_output_tokens). A cycle that was
            // collected but had no usage plots as 0 — the line returns to
            // zero rather than bridging idle periods, which would read as
            // continuous usage. Only cycles with no collected data at all
            // become gaps (null + spanGaps).
            // Combined view sums Input+Output per source (4 lines, matching
            // Total mode's grouping) instead of 8 separate lines — input vs.
            // output split is still available per-source on its own tab.
            const mapRateTotalFromLookup = (lookup) => {
                return allTimes.map(ts => {
                    const found = lookup.get(ts);
                    if (!found) return null;
                    return (found.delta_input_tokens || 0) + (found.delta_output_tokens || 0);
                });
            };

            const mapTotalFromLookup = (lookup) => allTimes.map(ts => {
                const found = lookup.get(ts);
                return found ? (found.input_tokens || 0) + (found.output_tokens || 0) : 0;
            });

            if (isTotal) {
                datasets = [
                    {
                        label: 'AGY',
                        data: mapTotalFromLookup(agyLookup),
                        borderColor: '#9b6dff',
                        backgroundColor: 'rgba(155, 109, 255, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                    {
                        label: 'OpenCode',
                        data: mapTotalFromLookup(opencodeLookup),
                        borderColor: '#4f8aff',
                        backgroundColor: 'rgba(79, 138, 255, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                    {
                        label: 'Codex',
                        data: mapTotalFromLookup(codexLookup),
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                    {
                        label: 'Claude',
                        data: mapTotalFromLookup(claudeLookup),
                        borderColor: '#d4a574',
                        backgroundColor: 'rgba(212, 165, 116, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                ];
            } else {
                datasets = [
                    {
                        label: 'AGY',
                        data: mapRateTotalFromLookup(agyLookup),
                        borderColor: '#9b6dff',
                        backgroundColor: 'rgba(155, 109, 255, 0.06)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'OpenCode',
                        data: mapRateTotalFromLookup(opencodeLookup),
                        borderColor: '#4f8aff',
                        backgroundColor: 'rgba(79, 138, 255, 0.06)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'Codex',
                        data: mapRateTotalFromLookup(codexLookup),
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.06)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'Claude',
                        data: mapRateTotalFromLookup(claudeLookup),
                        borderColor: '#d4a574',
                        backgroundColor: 'rgba(212, 165, 116, 0.06)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                ];
            }
        } else {
            let series = filterByTimeRange(history || [], timeRange);
            labels = series.map(d => formatLabel(d.timestamp));
            const c = COLORS[currentSource];

            if (isTotal) {
                datasets = [
                    {
                        label: 'Input Tokens',
                        data: series.map(d => d.input_tokens || 0),
                        borderColor: c.line,
                        backgroundColor: c.lineFill,
                        fill: true, tension: 0.4, pointRadius: 3, stack: 'stack0',
                    },
                    {
                        label: 'Output Tokens',
                        data: series.map(d => d.output_tokens || 0),
                        borderColor: c.outLine,
                        backgroundColor: c.outFill,
                        fill: true, tension: 0.4, pointRadius: 3, stack: 'stack0',
                    },
                ];
            } else {
                // Backend-served per-cycle deltas; zero-usage cycles plot as
                // 0 so the line returns to zero between bursts of activity.
                datasets = [
                    {
                        label: '\u0394 Input',
                        data: series.map(d => d.delta_input_tokens || 0),
                        borderColor: c.line,
                        backgroundColor: c.lineFill,
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 3,
                    },
                    {
                        label: '\u0394 Output',
                        data: series.map(d => d.delta_output_tokens || 0),
                        borderColor: c.outLine,
                        backgroundColor: c.outFill,
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 3,
                    },
                ];
            }
        }

        if (historyChartInstance) historyChartInstance.destroy();

        historyChartInstance = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                interaction: { intersect: false, mode: 'index' },
                scales: {
                    y: {
                        // Linear for both modes: Rate needs to render true
                        // zeros (log scales can't), so idle cycles visibly
                        // return the line to the axis.
                        type: 'linear',
                        beginAtZero: true,
                        stacked: isTotal,
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        title: { display: true, text: unitLabel, color: '#8a9fc8', font: { size: 10 } },
                    },
                    x: {
                        stacked: isTotal,
                        grid: { display: false },
                        ticks: { maxRotation: 30, font: { size: 10 } },
                    },
                },
                plugins: {
                    zoom: {
                        pan: { enabled: true, mode: 'x' },
                        zoom: {
                            wheel: { enabled: true, speed: 0.05 },
                            pinch: { enabled: true },
                            mode: 'x',
                        }
                    }
                }
            },
        });
    }

    // --- Quota ---
    async function fetchQuota() {
        try {
            let url = '/api/quota/latest';
            if (currentSource !== 'combined') {
                url = `/api/quota/${currentSource}/latest`;
            }
            const titleMap = {
                combined: 'Quota Limits',
                agy: 'AGY Quota Limits',
                opencode: 'OpenCode CLI Spending',
                codex: 'Codex Usage Limits',
                claude: 'Claude Usage Limits',
            };
            const titleEl = document.getElementById('quota-title');
            if (titleEl) titleEl.textContent = titleMap[currentSource] || 'Quota Limits';
            const resp = await fetch(url);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            renderQuota(data, currentSource);
        } catch (e) {
            console.error('fetchQuota error:', e);
            const container = document.getElementById('quota-cards');
            if (container) {
                container.innerHTML = '<div class="empty-state"><p>Failed to retrieve quota data.</p></div>';
            }
        }
    }

    function renderQuota(data, source) {
        const container = document.getElementById('quota-cards');
        const titleEl = document.getElementById('quota-title');

        container.className = 'quota-cards source-' + source;
        container.innerHTML = '';
        if (!data || Object.keys(data).length === 0) {
            container.innerHTML = '<div class="empty-state"><p>No quota details available.</p></div>';
            return;
        }

        for (const [src, quotaData] of Object.entries(data)) {
            if (!quotaData || Object.keys(quotaData).length === 0) continue;

            if (src === 'opencode') {
                const group = quotaData.opencode;
                if (group) {
                    const cost = group.total_cost || {};
                    renderOpenCodeCost(container, cost);
                }
            } else if (src === 'codex') {
                const group = quotaData.openai;
                if (group) {
                    const rateLimit = group.rate_limit || {};
                    const plan = quotaData._plan || 'free';
                    renderCodexQuota(container, rateLimit, plan);
                }
            } else if (src === 'claude') {
                renderClaudeQuota(container, quotaData);
            } else {
                const agyPlan = quotaData._plan || 'Free';
                for (const [group, limits] of Object.entries(quotaData)) {
                    if (group === '_plan') continue;
                    const card = document.createElement('div');
                    card.className = 'quota-group';
                    const groupLabel = group.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\bGpt\b/g, 'GPT');
                    let limitsHtml = '';
                    for (const [limitType, info] of Object.entries(limits)) {
                        const label = limitType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                        const pct = clampPct(info.remaining_pct);
                        const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
                        const seconds = info.refreshes_in_seconds || info.refreshes_in || 0;
                        let refreshStr = '';
                        if (seconds > 0) {
                            if (seconds < 3600) {
                                refreshStr = `Refreshes in ${Math.round(seconds / 60)} min`;
                            } else {
                                refreshStr = `Refreshes in ${Math.round(seconds / 3600)} hr`;
                            }
                        }
                        limitsHtml += `
                            <div class="quota-limit">
                                <div class="quota-limit-header">
                                    <span class="quota-limit-label">${escapeHtml(label)}</span>
                                    <span class="quota-limit-value">${pct.toFixed(1)}%</span>
                                </div>
                                <div class="quota-bar-bg">
                                    <div class="quota-bar-fill ${barColor}" style="width: ${pct}%"></div>
                                </div>
                                <div class="quota-refresh">${refreshStr}</div>
                            </div>
                        `;
                    }
                    const planBadge = src === 'agy' ? ` <span class="badge badge-agy">${escapeHtml(agyPlan)}</span>` : '';
                    card.innerHTML = `<h3>${escapeHtml(groupLabel)}${planBadge}</h3>${limitsHtml}`;
                    container.appendChild(card);
                }
            }
        }
    }

    function renderOpenCodeCost(container, cost) {
        const spent = cost.used || 0;
        const card = document.createElement('div');
        card.className = 'quota-group';
        card.innerHTML = `
            <h3>OpenCode <span class="badge badge-opencode">Free Tier</span></h3>
            <div class="quota-limit">
                <div class="quota-limit-header">
                     <span class="quota-limit-label">Total Cost</span>
                     <span class="quota-limit-value">$${spent.toFixed(2)}</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    }

    function renderCodexQuota(container, rateLimit, planType) {
        const card = document.createElement('div');
        card.className = 'quota-group';

        const planLabel = (planType || 'free').charAt(0).toUpperCase() + (planType || 'free').slice(1) + ' Plan';
        const hasLimit = rateLimit.remaining_pct !== undefined;

        if (hasLimit) {
            const pct = clampPct(rateLimit.remaining_pct);
            const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
            const seconds = rateLimit.refreshes_in || rateLimit.refreshes_in_seconds || 0;
            let refreshStr = '';
            if (seconds >= 86400) {
                refreshStr = `Resets in ${Math.round(seconds / 86400)} days`;
            } else if (seconds >= 3600) {
                refreshStr = `Resets in ${Math.round(seconds / 3600)} hr`;
            } else if (seconds > 0) {
                refreshStr = `Resets in ${Math.round(seconds / 60)} min`;
            }

            card.innerHTML = `
                <h3>Codex <span class="badge badge-codex">${escapeHtml(planLabel)}</span></h3>
                <div class="quota-limit">
                    <div class="quota-limit-header">
                        <span class="quota-limit-label">Monthly Limit (30d)</span>
                        <span class="quota-limit-value">${pct.toFixed(1)}% remaining</span>
                    </div>
                    <div class="quota-bar-bg">
                        <div class="quota-bar-fill ${barColor}" style="width: ${pct}%"></div>
                    </div>
                    <div class="quota-refresh">${refreshStr}</div>
                </div>
            `;
        } else {
            card.innerHTML = `
                <h3>Codex <span class="badge badge-codex">${escapeHtml(planLabel)}</span></h3>
                <div class="quota-limit">
                    <p style="color: #8a9fc8; font-size: 0.85rem; margin: 0.5rem 0;">
                        Rate limit details will populate once Codex activity is recorded.
                    </p>
                </div>
            `;
        }
        container.appendChild(card);
    }

    function renderClaudeQuota(container, data) {
        const card = document.createElement('div');
        card.className = 'quota-group';

        const plan = data._plan || 'Claude Pro';

        let limitsHtml = '';

        // Session (5h) limit
        const sessionGroup = data.session || {};
        const sessionLimit = sessionGroup.five_hour || {};
        if (sessionLimit.used !== undefined) {
            const remaining = clampPct(sessionLimit.remaining_pct);
            const barColor = remaining > 50 ? 'green' : remaining > 20 ? 'amber' : 'red';
            const seconds = sessionLimit.refreshes_in_seconds || 0;
            let refreshStr = '';
            if (seconds > 0) {
                if (seconds < 3600) {
                    refreshStr = `Resets in ${Math.round(seconds / 60)} min`;
                } else {
                    refreshStr = `Resets in ${Math.round(seconds / 3600)} hr`;
                }
            }
            limitsHtml += `
                <div class="quota-limit">
                    <div class="quota-limit-header">
                        <span class="quota-limit-label">Session (5h)</span>
                        <span class="quota-limit-value">${remaining.toFixed(1)}% left</span>
                    </div>
                    <div class="quota-bar-bg">
                        <div class="quota-bar-fill ${barColor}" style="width: ${remaining}%"></div>
                    </div>
                    <div class="quota-refresh">${refreshStr}</div>
                </div>
            `;
        }

        // Weekly limit
        const weeklyGroup = data.weekly || {};
        const weeklyAll = weeklyGroup.all_models || {};
        if (weeklyAll.used !== undefined) {
            const remaining = clampPct(weeklyAll.remaining_pct);
            const barColor = remaining > 50 ? 'green' : remaining > 20 ? 'amber' : 'red';
            const seconds = weeklyAll.refreshes_in_seconds || 0;
            let refreshStr = '';
            if (seconds > 0) {
                if (seconds >= 86400) {
                    refreshStr = `Resets in ${Math.round(seconds / 86400)} days`;
                } else if (seconds >= 3600) {
                    refreshStr = `Resets in ${Math.round(seconds / 3600)} hr`;
                } else {
                    refreshStr = `Resets in ${Math.round(seconds / 60)} min`;
                }
            }
            limitsHtml += `
                <div class="quota-limit">
                    <div class="quota-limit-header">
                        <span class="quota-limit-label">Weekly (All Models)</span>
                        <span class="quota-limit-value">${remaining.toFixed(1)}% left</span>
                    </div>
                    <div class="quota-bar-bg">
                        <div class="quota-bar-fill ${barColor}" style="width: ${remaining}%"></div>
                    </div>
                    <div class="quota-refresh">${refreshStr}</div>
                </div>
            `;
        }

        // Per-model weekly limits
        for (const [modelName, info] of Object.entries(weeklyGroup)) {
            if (modelName === 'all_models' || !info || typeof info !== 'object') continue;
            if (info.used === undefined) continue;
            const remaining = clampPct(info.remaining_pct);
            const barColor = remaining > 50 ? 'green' : remaining > 20 ? 'amber' : 'red';
            limitsHtml += `
                <div class="quota-limit">
                    <div class="quota-limit-header">
                        <span class="quota-limit-label">Weekly: ${escapeHtml(modelName)}</span>
                        <span class="quota-limit-value">${remaining.toFixed(1)}% left</span>
                    </div>
                    <div class="quota-bar-bg">
                        <div class="quota-bar-fill ${barColor}" style="width: ${remaining}%"></div>
                    </div>
                </div>
            `;
        }

        card.innerHTML = `
            <h3>Claude <span class="badge badge-claude">${escapeHtml(plan)}</span></h3>
            ${limitsHtml || '<p style="color: #8a9fc8; font-size: 0.85rem; margin: 0.5rem 0;">Claude quota data will appear once authenticated.</p>'}
        `;
        container.appendChild(card);
    }

    function escapeHtml(str) {
        return (str || '').replace(/[&<>"']/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    // --- Initial load + auto-refresh every 60s ---
    if (offline) {
        setStatus('offline', 'Offline');
    }
    refresh();
    setInterval(() => {
        if (offline) return;
        const elapsed = (Date.now() - lastFetchTime) / 1000;
        if (elapsed > 120) {
            setStatus('stale', 'Stale');
        }
        refresh();
    }, 60_000);
});
