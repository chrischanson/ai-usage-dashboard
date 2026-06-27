document.addEventListener('DOMContentLoaded', () => {
    let historyChartInstance = null;
    let modelChartInstance = null;
    let currentSource = 'combined';
    let timeRange = 'all';
    let mode = 'total';
    let cachedHistory = null;
    let cachedLatestOverview = null;

    if (typeof Chart !== 'undefined') {
        Chart.defaults.color = '#6b7fa3';
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
            accent: '#10a37f',
            line: '#10a37f',
            lineFill: 'rgba(16, 163, 127, 0.12)',
            outLine: '#19c37d',
            outFill: 'rgba(25, 195, 125, 0.08)',
            donut: ['#10a37f', '#19c37d', '#f59e0b', '#9b6dff', '#ec4899', '#f97316'],
        },
        combined: {
            accent: '#10c48a',
            donut: ['#9b6dff', '#4f8aff', '#10c48a', '#f59e0b', '#ec4899', '#f97316'],
        },
    };

    // --- Helpers ---
    function formatNum(n) {
        if (n == null) return '--';
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
        if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
        return Math.round(n).toLocaleString();
    }

    function setCard(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    // --- Tab switching ---
    document.querySelectorAll('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSource = btn.dataset.source;
            cachedHistory = null;
            cachedLatestOverview = null;
            refresh();
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
                    document.getElementById('time-range-label').textContent =
                        ' (' + timeRange.toUpperCase() + ')';
                } else if (cachedLatestOverview) {
                    renderOverview(cachedLatestOverview);
                    document.getElementById('time-range-label').textContent = '';
                }
                renderHistoryChart(cachedHistory);
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
            fetchLatest().then(() => {
                if (timeRange !== 'all' && cachedHistory) {
                    const overview = computeOverviewFromHistory(cachedHistory, timeRange);
                    if (overview) renderOverview(overview);
                }
            });
        });
    });

    // --- Fetch & render ---
    async function refresh() {
        await Promise.all([fetchLatest(), fetchHistory(), fetchQuota()]);
        if (timeRange !== 'all' && cachedHistory) {
            const overview = computeOverviewFromHistory(cachedHistory, timeRange);
            if (overview) renderOverview(overview);
        }
        document.getElementById('last-updated').textContent =
            'Last updated: ' + new Date().toLocaleTimeString();
    }

    async function fetchLatest() {
        try {
            let data;
            const deltasParam = mode === 'rate' ? '?deltas=true' : '';
            if (currentSource === 'combined') {
                const resp = await fetch('/api/usage/latest' + deltasParam);
                const raw = await resp.json();
                const agy = raw.agy || {};
                const opencode = raw.opencode || {};
                const codex = raw.codex || {};
                
                data = {
                    sessions: (agy.sessions || 0) + (opencode.sessions || 0) + (codex.sessions || 0),
                    messages: (agy.messages || 0) + (opencode.messages || 0) + (codex.messages || 0),
                    input_tokens: (agy.input_tokens || 0) + (opencode.input_tokens || 0) + (codex.input_tokens || 0),
                    output_tokens: (agy.output_tokens || 0) + (opencode.output_tokens || 0) + (codex.output_tokens || 0),
                    cache_read: (agy.cache_read || 0) + (opencode.cache_read || 0) + (codex.cache_read || 0),
                    models: [],
                    model_deltas: [],
                };

                const modelSrc = (mode === 'rate' ? 'model_deltas' : 'models');
                const agyModels = (agy[modelSrc] || []).map(m => ({ ...m, source: 'agy' }));
                const opencodeModels = (opencode[modelSrc] || []).map(m => ({ ...m, source: 'opencode' }));
                const codexModels = (codex[modelSrc] || []).map(m => ({ ...m, source: 'codex' }));
                data.models = [...agyModels, ...opencodeModels, ...codexModels].sort((a, b) => 
                    ((b.input_tokens || 0) + (b.output_tokens || 0)) - ((a.input_tokens || 0) + (a.output_tokens || 0))
                );
            } else {
                const resp = await fetch(`/api/usage/${currentSource}/latest` + deltasParam);
                data = await resp.json();
                const modelSrc = mode === 'rate' ? 'model_deltas' : 'models';
                if (data[modelSrc]) {
                    data.models = data[modelSrc];
                }
            }

            if (!data || Object.keys(data).length === 0) {
                cachedLatestOverview = null;
                setCard('total-sessions', '--');
                setCard('total-messages', '--');
                setCard('input-tokens', 'No data yet');
                setCard('output-tokens', '--');
                setCard('cache-reads', '--');
                document.getElementById('models-container').innerHTML =
                    '<p class="loading-msg">No data yet — polling every 10 min.</p>';
                if (modelChartInstance) { modelChartInstance.destroy(); modelChartInstance = null; }
                return;
            }
            cachedLatestOverview = data;
            renderOverview(data);
            renderModels(data.models || []);
            renderModelChart(data.models || []);
        } catch (e) {
            console.error('fetchLatest error:', e);
        }
    }

    async function fetchHistory() {
        try {
            if (currentSource === 'combined') {
                const results = await Promise.allSettled([
                    fetch('/api/usage/agy/history'),
                    fetch('/api/usage/opencode/history'),
                    fetch('/api/usage/codex/history')
                ]);
                let agyData = [], opencodeData = [], codexData = [];
                if (results[0].status === 'fulfilled') {
                    try { agyData = await results[0].value.json(); } catch (_) {}
                }
                if (results[1].status === 'fulfilled') {
                    try { opencodeData = await results[1].value.json(); } catch (_) {}
                }
                if (results[2].status === 'fulfilled') {
                    try { codexData = await results[2].value.json(); } catch (_) {}
                }
                cachedHistory = { agy: agyData, opencode: opencodeData, codex: codexData };
                renderHistoryChart(cachedHistory);
            } else {
                const resp = await fetch(`/api/usage/${currentSource}/history`);
                const data = await resp.json();
                cachedHistory = (data && data.length > 0) ? data : [];
                renderHistoryChart(cachedHistory);
            }
        } catch (e) {
            console.error('fetchHistory error:', e);
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
        const container = document.getElementById('models-container');
        if (!models.length) {
            container.innerHTML = '<p class="loading-msg">No model data available.</p>';
            return;
        }
        container.innerHTML = '';
        models.forEach(m => {
            const total = (m.input_tokens || 0) + (m.output_tokens || 0);
            const badgeHtml = m.source ? `<span class="badge badge-${m.source}">${m.source}</span>` : '';
            const div = document.createElement('div');
            div.className = 'model-item';
            div.innerHTML = `
                <div class="model-info">
                    <h4>${escapeHtml(m.model_name)}${badgeHtml}</h4>
                    <p>${formatNum(m.messages)} messages</p>
                </div>
                <div class="model-stats">
                    <div class="tokens">${formatNum(total)} tokens</div>
                    <p>in ${formatNum(m.input_tokens)} · out ${formatNum(m.output_tokens)}</p>
                </div>
            `;
            container.appendChild(div);
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

        const chartTitle = mode === 'rate' ? 'Model Tokens (this period)' : 'Model Distribution';

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
                        labels: { padding: 16, font: { size: 11 } },
                    },
                    title: {
                        display: true,
                        text: chartTitle,
                        color: '#6b7fa3',
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

    function computeRate(series, label) {
        if (!series || series.length === 0) return [];
        const result = [{ ...series[0], [label]: 0 }];
        for (let i = 1; i < series.length; i++) {
            const prev = series[i - 1];
            const curr = series[i];
            const delta = Math.max(0, (curr[label] || 0) - (prev[label] || 0));
            result.push({ ...curr, [label]: delta });
        }
        return result;
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
            return {
                sessions: (agy?.sessions || 0) + (opencode?.sessions || 0) + (codex?.sessions || 0),
                messages: (agy?.messages || 0) + (opencode?.messages || 0) + (codex?.messages || 0),
                input_tokens: (agy?.input_tokens || 0) + (opencode?.input_tokens || 0) + (codex?.input_tokens || 0),
                output_tokens: (agy?.output_tokens || 0) + (opencode?.output_tokens || 0) + (codex?.output_tokens || 0),
                cache_read: (agy?.cache_read || 0) + (opencode?.cache_read || 0) + (codex?.cache_read || 0),
            };
        }
        return sourceDelta(history) || null;
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
        let unitLabel = isTotal ? 'Tokens' : 'Δ tokens';

        if (currentSource === 'combined') {
            let agy = filterByTimeRange(history.agy || [], timeRange);
            let opencode = filterByTimeRange(history.opencode || [], timeRange);
            let codex = filterByTimeRange(history.codex || [], timeRange);

            const allTimes = Array.from(new Set([
                ...agy.map(d => d.timestamp),
                ...opencode.map(d => d.timestamp),
                ...codex.map(d => d.timestamp)
            ])).sort();

            labels = allTimes.map(formatLabel);

            const mapData = (list, key) => {
                return allTimes.map(ts => {
                    const found = list.find(d => d.timestamp === ts);
                    return found ? found[key] : null;
                });
            };

            if (isTotal) {
                const mapTotal = (list) => allTimes.map(ts => {
                    const found = list.find(d => d.timestamp === ts);
                    return found ? (found.input_tokens || 0) + (found.output_tokens || 0) : null;
                });
                datasets = [
                    {
                        label: 'AGY',
                        data: mapTotal(agy),
                        borderColor: '#9b6dff',
                        backgroundColor: 'rgba(155, 109, 255, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                    {
                        label: 'OpenCode',
                        data: mapTotal(opencode),
                        borderColor: '#4f8aff',
                        backgroundColor: 'rgba(79, 138, 255, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                    {
                        label: 'Codex',
                        data: mapTotal(codex),
                        borderColor: '#10a37f',
                        backgroundColor: 'rgba(16, 163, 127, 0.18)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                    },
                ];
            } else {
                agy = computeRate(agy, 'input_tokens');
                agy = computeRate(agy, 'output_tokens');
                opencode = computeRate(opencode, 'input_tokens');
                opencode = computeRate(opencode, 'output_tokens');
                codex = computeRate(codex, 'input_tokens');
                codex = computeRate(codex, 'output_tokens');
                datasets = [
                    {
                        label: 'AGY Input',
                        data: mapData(agy, 'input_tokens'),
                        borderColor: '#9b6dff',
                        backgroundColor: 'rgba(155, 109, 255, 0.03)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'AGY Output',
                        data: mapData(agy, 'output_tokens'),
                        borderColor: '#4f8aff',
                        backgroundColor: 'rgba(79, 138, 255, 0.02)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'OpenCode Input',
                        data: mapData(opencode, 'input_tokens'),
                        borderColor: '#10c48a',
                        backgroundColor: 'rgba(16, 196, 138, 0.03)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'OpenCode Output',
                        data: mapData(opencode, 'output_tokens'),
                        borderColor: '#f59e0b',
                        backgroundColor: 'rgba(245, 158, 11, 0.02)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'Codex Input',
                        data: mapData(codex, 'input_tokens'),
                        borderColor: '#10a37f',
                        backgroundColor: 'rgba(16, 163, 127, 0.03)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                    {
                        label: 'Codex Output',
                        data: mapData(codex, 'output_tokens'),
                        borderColor: '#19c37d',
                        backgroundColor: 'rgba(25, 195, 125, 0.02)',
                        fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                    },
                ];
            }
        } else {
            let series = filterByTimeRange(history, timeRange);
            labels = series.map(d => formatLabel(d.timestamp));
            const c = COLORS[currentSource];

            if (isTotal) {
                datasets = [
                    {
                        label: 'Input Tokens',
                        data: series.map(d => d.input_tokens),
                        borderColor: c.line,
                        backgroundColor: c.lineFill,
                        fill: true, tension: 0.4, pointRadius: 3, stack: 'stack0',
                    },
                    {
                        label: 'Output Tokens',
                        data: series.map(d => d.output_tokens),
                        borderColor: c.outLine,
                        backgroundColor: c.outFill,
                        fill: true, tension: 0.4, pointRadius: 3, stack: 'stack0',
                    },
                ];
            } else {
                series = computeRate(series, 'input_tokens');
                series = computeRate(series, 'output_tokens');
                datasets = [
                    {
                        label: 'Δ Input',
                        data: series.map(d => d.input_tokens),
                        borderColor: c.line,
                        backgroundColor: c.lineFill,
                        fill: true, tension: 0.4, pointRadius: 3,
                    },
                    {
                        label: 'Δ Output',
                        data: series.map(d => d.output_tokens),
                        borderColor: c.outLine,
                        backgroundColor: c.outFill,
                        fill: true, tension: 0.4, pointRadius: 3,
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
                        beginAtZero: mode === 'rate',
                        stacked: isTotal,
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        title: { display: true, text: unitLabel, color: '#6b7fa3', font: { size: 10 } },
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
                agy: 'Antigravity Quota Limits',
                opencode: 'OpenCode CLI Spending',
                codex: 'Codex (OpenAI) Usage Limits',
            };
            document.getElementById('quota-title').textContent = titleMap[currentSource] || 'Quota Limits';
            const resp = await fetch(url);
            const data = await resp.json();
            renderQuota(data, currentSource);
        } catch (e) {
            console.error('fetchQuota error:', e);
        }
    }

    function renderQuota(data, source) {
        const container = document.getElementById('quota-cards');
        const titleEl = document.getElementById('quota-title');

        container.className = 'quota-cards source-' + source;
        container.innerHTML = '';
        if (!data || Object.keys(data).length === 0) {
            container.innerHTML = '<p class="loading-msg">No quota data available.</p>';
            return;
        }

        // data is always keyed by source: { 'agy': {...}, 'opencode': {...}, 'codex': {...} }
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
            } else {
                // AGY style quota (model groups with limits)
                const agyPlan = quotaData._plan || 'Free';
                for (const [group, limits] of Object.entries(quotaData)) {
                    if (group === '_plan') continue;
                    const card = document.createElement('div');
                    card.className = 'quota-group';
                    const groupLabel = group.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                    let limitsHtml = '';
                    for (const [limitType, info] of Object.entries(limits)) {
                        const label = limitType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                        const pct = info.remaining_pct || 0;
                        const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
                        const seconds = info.refreshes_in_seconds || info.refreshes_in || 0;
                        let refreshStr = '';
                        if (seconds > 0) {
                            if (seconds < 3600) {
                                refreshStr = `Refreshes in ${Math.round(seconds / 60)}m`;
                            } else {
                                refreshStr = `Refreshes in ${Math.round(seconds / 3600)}h`;
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
            const pct = rateLimit.remaining_pct;
            const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
            const seconds = rateLimit.refreshes_in || rateLimit.refreshes_in_seconds || 0;
            let refreshStr = '';
            if (seconds >= 86400) {
                refreshStr = `Resets in ${Math.round(seconds / 86400)}d`;
            } else if (seconds >= 3600) {
                refreshStr = `Resets in ${Math.round(seconds / 3600)}h`;
            } else if (seconds > 0) {
                refreshStr = `Resets in ${Math.round(seconds / 60)}m`;
            }

            card.innerHTML = `
                <h3>Codex (OpenAI) <span class="badge badge-codex">${escapeHtml(planLabel)}</span></h3>
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
                <h3>Codex (OpenAI) <span class="badge badge-codex">${escapeHtml(planLabel)}</span></h3>
                <div class="quota-limit">
                    <p style="color: #6b7fa3; font-size: 0.85rem; margin: 0.5rem 0;">
                        Rate limit data will populate once Codex API calls are registered.
                    </p>
                </div>
            `;
        }
        container.appendChild(card);
    }

    function escapeHtml(str) {
        return (str || '').replace(/[&<>"']/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    // --- Initial load + auto-refresh every 60s ---
    refresh();
    setInterval(refresh, 60_000);
});
