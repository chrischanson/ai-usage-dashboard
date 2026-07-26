import { state } from './state.js';
import { filterByTimeRange } from './format.js';

export function computeOverviewFromHistory(history, range) {
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
    if (state.currentSource === 'combined') {
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

export function computeModelsFromHistory(history, range) {
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
                cost: Math.max(0, (m.cost || 0) - (prev.cost || 0)),
            };
            if (dm.messages > 0 || dm.input_tokens > 0 || dm.output_tokens > 0) {
                deltas.push(dm);
            }
        });
        return deltas.length > 0 ? deltas : null;
    }
    if (state.currentSource === 'combined') {
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
