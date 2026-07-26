import { state } from './state.js';
import { formatModelName, parseTs, formatLabel, formatNum } from './format.js';
import { COLORS, TOKENS } from './colors.js';

// Mutable chart instances that can be accessed and modified from other modules
export const charts = {
    historyChartInstance: null,
    modelChartInstance: null,
};

export function renderModelChart(models) {
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js is not loaded. Skipping model chart rendering.');
        return;
    }
    const ctx = document.getElementById('modelChart').getContext('2d');
    const tokens = TOKENS();

    // Take top 7 models, sum the rest into "Other"
    const modelData = models.map(m => ({
        label: (() => {
            const name = formatModelName(m.model_name, m.source);
            return m.source ? `${name} (${m.source})` : name;
        })(),
        source: m.source || state.currentSource,
        value: Math.max(0, (m.input_tokens || 0) + (m.output_tokens || 0)),
    }))
    .sort((a, b) => b.value - a.value);

    let labels = [];
    let data = [];
    let totalTokens = 0;

    // Take top 7 models
    for (let i = 0; i < Math.min(7, modelData.length); i++) {
        labels.push(modelData[i].label);
        data.push(modelData[i].value);
        totalTokens += modelData[i].value;
    }

    // Fold the tail into one slice. A single leftover model is shown by name
    // instead — "Other (1 model)" hides a name for no benefit.
    if (modelData.length === 8) {
        labels.push(modelData[7].label);
        data.push(modelData[7].value);
        totalTokens += modelData[7].value;
    } else if (modelData.length > 8) {
        let otherSum = 0;
        const otherCount = modelData.length - 7;
        for (let i = 7; i < modelData.length; i++) {
            otherSum += modelData[i].value;
        }
        labels.push(`Other (${otherCount} models)`);
        data.push(otherSum);
        totalTokens += otherSum;
    }

    // Slices are hued by the model's SOURCE, not by its rank. The stacked chart
    // beside this one already teaches the reader that violet=AGY, blue=OpenCode,
    // etc.; assigning those same hues by rank here would contradict it. Models
    // sharing a source step through tints of that source's hue.
    const SOURCE_HUE = {
        agy: tokens.agyColor,
        opencode: tokens.opencodeColor,
        codex: tokens.codexColor,
        claude: tokens.claudeColor,
        combined: tokens.signal,
    };
    const seenPerSource = {};
    const palette = labels.map((label, i) => {
        if (label.startsWith('Other (')) return tokens.dvOther;
        const src = (modelData[i] && modelData[i].source) || 'combined';
        const base = SOURCE_HUE[src] || tokens.dvOther;
        const step = seenPerSource[src] = (seenPerSource[src] || 0) + 1;
        // First model of a source keeps the pure hue; each subsequent one is
        // mixed further toward the page ink so it stays legibly distinct.
        if (step === 1) return base;
        const pct = Math.max(35, 100 - (step - 1) * 22);
        return `color-mix(in oklch, ${base} ${pct}%, ${tokens.ink})`;
    });

    if (charts.modelChartInstance) charts.modelChartInstance.destroy();

    const chartTitle = 'Model Distribution';

    // Center-text plugin to show total tokens
    const centerTextPlugin = {
        id: 'centerText',
        afterDatasetsDraw(chart) {
            const { ctx } = chart;
            const { left, top, width, height } = chart.chartArea;
            const centerX = left + width / 2;
            const centerY = top + height / 2;

            ctx.save();
            ctx.font = '500 16px "IBM Plex Mono"';
            ctx.fillStyle = tokens.ink;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            const text = formatNum(totalTokens);
            ctx.fillText(text, centerX, centerY - 8);

            ctx.font = '400 11px "IBM Plex Mono"';
            ctx.fillStyle = tokens.inkFaint;
            ctx.fillText('tokens', centerX, centerY + 12);

            ctx.restore();
        },
    };

    charts.modelChartInstance = new Chart(ctx, {
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
        plugins: [centerTextPlugin],
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    align: 'start',
                    labels: {
                        padding: 12,
                        font: { size: 11 },
                        color: tokens.inkDim,
                        boxWidth: 10,
                    },
                },
                title: {
                    display: false,
                    text: chartTitle,
                },
            },
        },
    });
}

export function renderHistoryChart(history) {
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js is not loaded. Skipping history chart rendering.');
        return;
    }
    const ctx = document.getElementById('historyChart').getContext('2d');
    const tokens = TOKENS();
    let datasets = [];
    let labels = [];
    const isTotal = state.mode === 'total';
    let unitLabel = isTotal ? 'Tokens' : 'Δ tokens';

    if (state.currentSource === 'combined') {
        const agyFull = history.agy || [];
        const opencodeFull = history.opencode || [];
        const codexFull = history.codex || [];
        const claudeFull = history.claude || [];

        // The API serves cumulative-since-first-observation totals in
        // input_tokens/output_tokens and per-cycle increments in
        // delta_input_tokens/delta_output_tokens (derived in db.py from
        // the raw stored observations) — plot them as-is.
        let agy = filterByTimeRangeLocal(agyFull, state.timeRange);
        let opencode = filterByTimeRangeLocal(opencodeFull, state.timeRange);
        let codex = filterByTimeRangeLocal(codexFull, state.timeRange);
        let claude = filterByTimeRangeLocal(claudeFull, state.timeRange);

        const allTimes = Array.from(new Set([
            ...agy.map(d => d.timestamp),
            ...opencode.map(d => d.timestamp),
            ...codex.map(d => d.timestamp),
            ...claude.map(d => d.timestamp)
        ])).sort();

        labels = allTimes.map(formatLabel);

        // Cache parsed date times to avoid repetitive parsing inside loops
        const parsedTimeCache = new Map();
        function getParsedTime(ts) {
            let val = parsedTimeCache.get(ts);
            if (val === undefined) {
                const dt = parseTs(ts);
                val = dt ? dt.getTime() : 0;
                parsedTimeCache.set(ts, val);
            }
            return val;
        }

        // Forward-fill: for each unified timestamp, carry forward the last known
        // value from each source so gaps don't cause dips in stacked charts.
        const MS_TOLERANCE = 30 * 60 * 1000; // 30 minutes
        function buildFilledLookup(data) {
            const lookup = new Map();
            let lastEntry = null;
            let dataIdx = 0;
            for (const ts of allTimes) {
                const t = getParsedTime(ts);
                while (dataIdx < data.length) {
                    const dTs = data[dataIdx].timestamp;
                    const dTime = getParsedTime(dTs);
                    if (dTime <= t) {
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
                    borderColor: tokens.agyColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.agyColor} 18%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                },
                {
                    label: 'OpenCode',
                    data: mapTotalFromLookup(opencodeLookup),
                    borderColor: tokens.opencodeColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.opencodeColor} 18%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                },
                {
                    label: 'Codex',
                    data: mapTotalFromLookup(codexLookup),
                    borderColor: tokens.codexColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.codexColor} 18%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                },
                {
                    label: 'Claude',
                    data: mapTotalFromLookup(claudeLookup),
                    borderColor: tokens.claudeColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.claudeColor} 18%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2, stack: 'stack0',
                },
            ];
        } else {
            datasets = [
                {
                    label: 'AGY',
                    data: mapRateTotalFromLookup(agyLookup),
                    borderColor: tokens.agyColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.agyColor} 6%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                },
                {
                    label: 'OpenCode',
                    data: mapRateTotalFromLookup(opencodeLookup),
                    borderColor: tokens.opencodeColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.opencodeColor} 6%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                },
                {
                    label: 'Codex',
                    data: mapRateTotalFromLookup(codexLookup),
                    borderColor: tokens.codexColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.codexColor} 6%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                },
                {
                    label: 'Claude',
                    data: mapRateTotalFromLookup(claudeLookup),
                    borderColor: tokens.claudeColor,
                    backgroundColor: `color-mix(in oklch, ${tokens.claudeColor} 6%, transparent)`,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 2,
                },
            ];
        }
    } else {
        let series = filterByTimeRangeLocal(history || [], state.timeRange);
        labels = series.map(d => formatLabel(d.timestamp));
        const c = COLORS[state.currentSource];

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
                    label: 'Δ Input',
                    data: series.map(d => d.delta_input_tokens || 0),
                    borderColor: c.line,
                    backgroundColor: c.lineFill,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 3,
                },
                {
                    label: 'Δ Output',
                    data: series.map(d => d.delta_output_tokens || 0),
                    borderColor: c.outLine,
                    backgroundColor: c.outFill,
                    fill: true, tension: 0.4, spanGaps: true, pointRadius: 3,
                },
            ];
        }
    }

    if (charts.historyChartInstance) charts.historyChartInstance.destroy();

    charts.historyChartInstance = new Chart(ctx, {
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
                    grid: {
                        color: `color-mix(in oklch, ${tokens.line} 40%, transparent)`,
                    },
                    title: {
                        display: true,
                        text: unitLabel,
                        color: tokens.inkDim,
                        font: { size: 10 },
                    },
                    ticks: {
                        color: tokens.inkFaint,
                        font: { family: "'IBM Plex Mono', monospace", size: 10 },
                    },
                },
                x: {
                    stacked: isTotal,
                    grid: { display: false },
                    ticks: {
                        // A week of 10-minute cycles is ~1000 points. Left to
                        // itself Chart.js prints a rotated label per gridline and
                        // they overlap into an unreadable band, so cap the count
                        // and keep them horizontal.
                        maxRotation: 0,
                        autoSkip: true,
                        maxTicksLimit: 6,
                        font: { family: "'IBM Plex Mono', monospace", size: 10 },
                        color: tokens.inkFaint,
                    },
                },
            },
            plugins: {
                tooltip: {
                    backgroundColor: tokens.surface2,
                    borderColor: tokens.edge,
                    borderWidth: 1,
                    titleColor: tokens.ink,
                    bodyColor: tokens.ink,
                    bodyFont: { family: "'IBM Plex Mono', monospace" },
                    titleFont: { size: 12, weight: 'bold' },
                    padding: 8,
                },
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

// Helper function to filter by time range (imported here to avoid circular import)
function filterByTimeRangeLocal(data, range) {
    if (!Array.isArray(data) || range === 'all' || !data.length) return data;
    const lastTsVal = parseTs(data[data.length - 1].timestamp);
    if (!lastTsVal) return data;
    const dataEnd = lastTsVal.getTime();
    const ms = {
        '1h': 3600000, '6h': 21600000,
        '1d': 86400000, '1w': 604800000, '1m': 2592000000, '3m': 7776000000
    }[range] || 86400000;
    const cutoff = dataEnd - ms;

    // Binary search for the first element >= cutoff (since input is pre-sorted)
    let low = 0;
    let high = data.length - 1;
    let resultIdx = data.length;

    while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const midTs = parseTs(data[mid].timestamp);
        if (midTs && midTs.getTime() >= cutoff) {
            resultIdx = mid;
            high = mid - 1;
        } else {
            low = mid + 1;
        }
    }
    return data.slice(resultIdx);
}

// Initialize dblclick handler for resetZoom on history chart
const canvas = document.getElementById('historyChart');
if (canvas) {
    canvas.addEventListener('dblclick', () => {
        if (charts.historyChartInstance && typeof charts.historyChartInstance.resetZoom === 'function') {
            charts.historyChartInstance.resetZoom();
        }
    });
}

// Initialize Chart.js defaults
if (typeof Chart !== 'undefined') {
    const tokens = TOKENS();
    Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
    Chart.defaults.color = tokens.inkDim;
}
