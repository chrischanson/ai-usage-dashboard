// Clamp values interpolated into inline style="width: N%" so a malformed
// upstream reading can't produce a non-numeric or out-of-range style value.
export function clampPct(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
}

export function formatNum(n) {
    if (n == null) return '--';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
    if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
    return Math.round(n).toLocaleString();
}

export function formatCost(n) {
    if (n == null || n === 0) return '--';
    if (n < 0.01) return '<$0.01';
    return '$' + n.toFixed(2);
}

export function formatModelName(name, source) {
    // Show what the source actually reported.
    //
    // This used to map identifiers onto a small set of hardcoded display names,
    // which silently mislabelled most real models — claude-opus-5 rendered as
    // "Claude 3 Opus", every gpt-5.x as "GPT-4o", gemini-2.5-pro as
    // "Gemini 2.5 Flash" — and collapsed distinct models onto one label
    // (gemini-3-flash-a and gemini-3-flash-b both became "Gemini 3.6 Flash").
    // On a dashboard whose job is attributing tokens and cost, renaming one
    // model to another is the worst kind of wrong. Same rule as everywhere
    // else here: no data beats wrong data, and the raw id is real data.
    if (!name) return 'Unknown';
    let str = String(name).trim();

    // Drop only a provider prefix that repeats the source we already show in
    // the badge ("opencode/deepseek-v4-flash" under OpenCode). A prefix that
    // differs is kept, because it is what distinguishes
    // deepseek/deepseek-v4-flash from opencode/deepseek-v4-flash.
    if (source) {
        const prefix = String(source).toLowerCase() + '/';
        if (str.toLowerCase().startsWith(prefix)) str = str.slice(prefix.length);
    }

    return str;
}

export function escapeHtml(str) {
    return (str || '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function parseTs(ts) {
    if (!ts) return null;
    const d = new Date(ts.replace(' ', 'T') + 'Z');
    return isNaN(d) ? null : d;
}

export function filterByTimeRange(data, range) {
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

const labelCache = new Map();
export function formatLabel(ts) {
    const isMobile = window.innerWidth <= 640;
    const cacheKey = ts + '_' + isMobile;
    let cachedVal = labelCache.get(cacheKey);
    if (cachedVal !== undefined) return cachedVal;

    const dt = parseTs(ts);
    if (!dt) return ts;
    let formatted;
    if (isMobile) {
        formatted = dt.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
    } else {
        formatted = dt.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    labelCache.set(cacheKey, formatted);
    return formatted;
}
