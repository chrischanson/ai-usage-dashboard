const FALLBACK_COLORS = [
    'oklch(0.70 0.16 300)', // violet
    'oklch(0.72 0.12 250)', // blue
    'oklch(0.75 0.13 165)', // emerald
    'oklch(0.72 0.10 60)',  // copper
    'oklch(0.68 0.14 30)',  // amber
    'oklch(0.65 0.15 340)', // rose
];

let sources = [];

async function loadSources() {
    try {
        const resp = await fetch('/api/sources');
        if (!resp.ok) throw new Error('Failed to fetch sources');
        const data = await resp.json();
        
        let colorIdx = 0;
        sources = data.map(src => {
            const color = src.color || FALLBACK_COLORS[colorIdx++ % FALLBACK_COLORS.length];
            document.documentElement.style.setProperty(`--src-${src.name}`, color);
            return {
                ...src,
                color
            };
        });
        
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
