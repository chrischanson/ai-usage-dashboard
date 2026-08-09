// Reads CSS custom properties from the DOM once at init and exposes the COLORS map,
// plus the resolved token values for Chart.js defaults.

import { getSources } from './sources.js';

let cachedColors = null;
let cachedTokens = null;

// Helper: read a CSS custom property from the root element
function getToken(name) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return value ? value.trim() : '';
}

// Lazy initialization: read tokens once and cache them
function initializeTokens() {
    if (cachedTokens !== null) return cachedTokens;

    const tokens = {
        ink: getToken('--ink'),
        inkDim: getToken('--ink-dim'),
        inkFaint: getToken('--ink-faint'),
        line: getToken('--line'),
        edge: getToken('--edge'),
        surface: getToken('--surface'),
        surface2: getToken('--surface-2'),
        signal: getToken('--signal'),
        dv5: getToken('--dv-5'),
        dv6: getToken('--dv-6'),
        dv7: getToken('--dv-7'),
        dvOther: getToken('--dv-other'),
    };

    const sources = getSources();
    sources.forEach(src => {
        tokens[`${src.name}Color`] = src.color || getToken(`--src-${src.name}`);
    });

    cachedTokens = tokens;
    return tokens;
}

// Lazy initialization: create the COLORS map from tokens
function initializeColors() {
    if (cachedColors !== null) return cachedColors;

    const tokens = initializeTokens();

    // Helper to create lineFill with 14% opacity using color-mix
    const makeLineFill = (color) => `color-mix(in oklch, ${color} 14%, transparent)`;

    const colors = {};
    const sources = getSources();
    
    // Build the dynamic donut palette
    const donutPalette = sources.map(src => tokens[`${src.name}Color`]);
    donutPalette.push(tokens.dv5, tokens.dv6, tokens.dv7);

    sources.forEach((src, index) => {
        const nextSrc = sources[(index + 1) % sources.length];
        const srcColor = tokens[`${src.name}Color`];
        const nextSrcColor = tokens[`${nextSrc.name}Color`];
        
        colors[src.name] = {
            accent: srcColor,
            line: srcColor,
            lineFill: makeLineFill(srcColor),
            outLine: nextSrcColor,
            outFill: makeLineFill(nextSrcColor),
            donut: donutPalette,
        };
    });

    colors.combined = {
        accent: tokens.signal,
        donut: donutPalette,
    };

    cachedColors = colors;
    return colors;
}

// Export as a Proxy that returns the initialized colors on access
export const COLORS = new Proxy({}, {
    get(target, prop) {
        const colors = initializeColors();
        return colors[prop];
    },
});

// Export function to get resolved token values
export function TOKENS() {
    return initializeTokens();
}

// Flush the caches so the next call to TOKENS() / COLORS[…] re-reads from
// the live DOM and the (now populated) sources list.  Must be called after
// sourcesReady resolves — the initial cache is often poisoned because
// getSources() returns [] while the /api/sources fetch is still in-flight.
export function resetCache() {
    cachedTokens = null;
    cachedColors = null;
}
