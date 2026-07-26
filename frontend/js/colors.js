// Reads CSS custom properties from the DOM once at init and exposes the COLORS map,
// plus the resolved token values for Chart.js defaults.

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
        agyColor: getToken('--src-agy'),
        opencodeColor: getToken('--src-opencode'),
        codexColor: getToken('--src-codex'),
        claudeColor: getToken('--src-claude'),
        dv5: getToken('--dv-5'),
        dv6: getToken('--dv-6'),
        dv7: getToken('--dv-7'),
        dvOther: getToken('--dv-other'),
    };

    cachedTokens = tokens;
    return tokens;
}

// Lazy initialization: create the COLORS map from tokens
function initializeColors() {
    if (cachedColors !== null) return cachedColors;

    const tokens = initializeTokens();

    // Helper to create lineFill with 14% opacity using color-mix
    const makeLineFill = (color) => `color-mix(in oklch, ${color} 14%, transparent)`;

    const colors = {
        agy: {
            accent: tokens.agyColor,
            line: tokens.agyColor,
            lineFill: makeLineFill(tokens.agyColor),
            outLine: tokens.opencodeColor,
            outFill: makeLineFill(tokens.opencodeColor),
            donut: [tokens.agyColor, tokens.opencodeColor, tokens.codexColor, tokens.claudeColor, tokens.dv5, tokens.dv6, tokens.dv7],
        },
        opencode: {
            accent: tokens.opencodeColor,
            line: tokens.opencodeColor,
            lineFill: makeLineFill(tokens.opencodeColor),
            outLine: tokens.codexColor,
            outFill: makeLineFill(tokens.codexColor),
            donut: [tokens.agyColor, tokens.opencodeColor, tokens.codexColor, tokens.claudeColor, tokens.dv5, tokens.dv6, tokens.dv7],
        },
        codex: {
            accent: tokens.codexColor,
            line: tokens.codexColor,
            lineFill: makeLineFill(tokens.codexColor),
            outLine: tokens.claudeColor,
            outFill: makeLineFill(tokens.claudeColor),
            donut: [tokens.agyColor, tokens.opencodeColor, tokens.codexColor, tokens.claudeColor, tokens.dv5, tokens.dv6, tokens.dv7],
        },
        claude: {
            accent: tokens.claudeColor,
            line: tokens.claudeColor,
            lineFill: makeLineFill(tokens.claudeColor),
            outLine: tokens.agyColor,
            outFill: makeLineFill(tokens.agyColor),
            donut: [tokens.agyColor, tokens.opencodeColor, tokens.codexColor, tokens.claudeColor, tokens.dv5, tokens.dv6, tokens.dv7],
        },
        combined: {
            accent: tokens.signal,
            donut: [tokens.agyColor, tokens.opencodeColor, tokens.codexColor, tokens.claudeColor, tokens.dv5, tokens.dv6, tokens.dv7],
        },
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
