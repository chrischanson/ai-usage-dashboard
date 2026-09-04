const FALLBACK_COLORS = [
    'oklch(0.70 0.16 300)', // violet
    'oklch(0.72 0.12 250)', // blue
    'oklch(0.75 0.13 165)', // emerald
    'oklch(0.72 0.10 60)',  // copper
    'oklch(0.68 0.14 30)',  // amber
    'oklch(0.65 0.15 340)', // rose
];

// Source ids end up in CSS custom property names, generated CSS class
// selectors, and DOM attributes/classes. The backend already enforces this
// slug shape at load time (backend/provider_loader.py); this is a
// belt-and-braces client-side guard against a stale/cached API response.
const VALID_ID_RE = /^[a-z0-9_-]+$/;

let sources = [];

async function loadSources() {
    try {
        const resp = await fetch('/api/sources');
        if (!resp.ok) throw new Error('Failed to fetch sources');
        const data = await resp.json();

        const validData = data.filter(src => {
            const isValid = typeof src.name === 'string' && VALID_ID_RE.test(src.name);
            if (!isValid) {
                console.error('Skipping source with invalid id:', src && src.name);
            }
            return isValid;
        });

        let colorIdx = 0;
        sources = validData.map(src => {
            const color = src.color || FALLBACK_COLORS[colorIdx++ % FALLBACK_COLORS.length];
            document.documentElement.style.setProperty(`--src-${src.name}`, color);
            return {
                ...src,
                color
            };
        });

        // These per-source selectors (.tab.active[data-source], .badge-X,
        // .source-X) can't be expressed via classList/dataset -- CSS rules
        // have to exist as text somewhere, and index.css only hardcodes them
        // for the sources known at the time it was written. Generating them
        // here is what lets a newly-added provider YAML render correctly
        // (tab accent, badge style, source-colored text) without also
        // editing the static stylesheet. Ids are slug-validated above, so
        // interpolating them into this generated CSS text is safe; the
        // rules' bodies otherwise contain only static values.
        const style = document.createElement('style');
        style.textContent = sources.map(src => `
            .tab.active[data-source="${src.name}"] { color: var(--src-${src.name}); }
            .badge-${src.name} {
                background: var(--surface-2);
                color: var(--ink-dim);
                border: none;
                font-family: 'IBM Plex Mono', monospace;
                font-weight: 600;
                font-size: 0.55rem;
                padding: 0.2rem 0.4rem;
                letter-spacing: 0.08em;
            }
            .source-${src.name} { color: var(--src-${src.name}); }
        `).join('\n');
        document.head.appendChild(style);
    } catch (e) {
        console.error('Error loading sources:', e);
        sources = [];
    }
}

export const ready = loadSources();

export function getSources() {
    return sources;
}

export function getSourceNames() {
    return sources.map(s => s.name);
}

export function getSourceColor(name) {
    const src = sources.find(s => s.name === name);
    return src ? src.color : null;
}

export function getSourceDisplayName(name) {
    const src = sources.find(s => s.name === name);
    return src ? src.display_name : name;
}
