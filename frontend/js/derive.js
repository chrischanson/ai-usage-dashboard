import { state } from './state.js';
import { filterByTimeRange } from './format.js';
import { getSourceNames } from './sources.js';

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
        const sourceNames = getSourceNames();
        const overview = {
            sessions: 0,
            messages: 0,
            input_tokens: 0,
            output_tokens: 0,
            cache_read: 0,
        };
        
        sourceNames.forEach(name => {
            const delta = sourceDelta(history[name]);
            if (delta) {
                overview.sessions += (delta.sessions || 0);
                overview.messages += (delta.messages || 0);
                overview.input_tokens += (delta.input_tokens || 0);
                overview.output_tokens += (delta.output_tokens || 0);
                overview.cache_read += (delta.cache_read || 0);
            }
        });
        
        return overview;
    }
    return sourceDelta(history) || null;
}

export function computeModelsFromHistory(history, range) {
    if (range === 'all' || !history) return null;
    function sourceModels(data) {
        if (!data || data.length < 2) return null;
        const filtered = filterByTimeRange(data, range);
        if (filtered.length < 2) return null;
        const last = filtered[filtered.length - 1];

        // Baseline each model at its EARLIEST reading inside the window, not at
        // the window's first cycle. A model that starts being reported partway
        // through is absent from cycle 0, and treating that absence as a zero
        // baseline charges its entire lifetime total to this window — one model
        // showed 19.89M of "usage in the last day" against a real daily total
        // of 3.08M. Only growth observed inside the window counts.
        const firstModels = {};
        for (const row of filtered) {
            (row.models || []).forEach(function(m) {
                if (!(m.model_name in firstModels)) firstModels[m.model_name] = m;
            });
        }
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
        const combined = [];
        const sourceNames = getSourceNames();
        sourceNames.forEach(name => {
            const models = sourceModels(history[name]);
            (models || []).forEach(m => {
                combined.push(Object.assign({}, m, { source: name }));
            });
        });
        return combined.sort(function(a, b) {
            return ((b.input_tokens || 0) + (b.output_tokens || 0)) - ((a.input_tokens || 0) + (a.output_tokens || 0));
        });
    }
    return sourceModels(history) || [];
}
