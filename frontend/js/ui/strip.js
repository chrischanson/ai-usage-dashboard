// The cycle strip — the header's cadence instrument.
//
// The poller writes one aligned row per source every `poll_interval_s`. Each
// tick is one EXPECTED cycle, derived by walking back from the newest observed
// cycle in whole intervals. A tick is filled only when that exact cycle_ts is
// present in the fetched history; otherwise it stays hollow. Cycles named in an
// integrity warning are marked as repaired.
//
// The rule this obeys: no data beats wrong data. The strip never invents a tick
// and never fills one it cannot account for.

import { state } from '../state.js';

const TICK_COUNT = 12;
const DEFAULT_INTERVAL_S = 600;

let cadence = { pollIntervalS: DEFAULT_INTERVAL_S, latestCycleTs: null, nextCycleTs: null };
let repairedCycles = new Set();
let countdownTimer = null;

/** Record the `_meta` block from /api/usage/latest. Falls back to the modal
 *  delta between recent cycles if the server predates the field. */
export function setCadence(meta, historyCycles) {
    if (meta && meta.poll_interval_s) {
        cadence = {
            pollIntervalS: meta.poll_interval_s,
            latestCycleTs: meta.latest_cycle_ts || null,
            nextCycleTs: meta.next_cycle_ts || null,
        };
        return;
    }
    const interval = modalDelta(historyCycles) || DEFAULT_INTERVAL_S;
    const latest = historyCycles && historyCycles.length
        ? historyCycles[historyCycles.length - 1]
        : null;
    cadence = {
        pollIntervalS: interval,
        latestCycleTs: latest,
        nextCycleTs: latest ? latest + interval : null,
    };
}

/** Most common gap between consecutive cycles — the observed poll interval. */
function modalDelta(cycles) {
    if (!cycles || cycles.length < 3) return null;
    const counts = new Map();
    for (let i = 1; i < cycles.length; i++) {
        const d = cycles[i] - cycles[i - 1];
        if (d > 0) counts.set(d, (counts.get(d) || 0) + 1);
    }
    let best = null, bestN = 0;
    for (const [d, n] of counts) {
        if (n > bestN) { best = d; bestN = n; }
    }
    return best;
}

/** Integrity warnings mention the cycles they repaired, e.g.
 *  "agy cycle 1785084000: model tokens sum to ...". Pull those ids out so the
 *  strip can anchor the banner to the exact ticks involved. */
export function setIntegrityWarnings(warnings) {
    const found = new Set();
    (warnings || []).forEach((w) => {
        const re = /cycle (\d{6,})/g;
        let m;
        while ((m = re.exec(String(w))) !== null) found.add(Number(m[1]));
    });
    repairedCycles = found;
}

/** Every cycle_ts present in the fetched history, across all sources. */
export function collectCycles(history) {
    if (!history) return [];
    const seen = new Set();
    const buckets = Array.isArray(history)
        ? [history]
        : Object.values(history).filter(Array.isArray);
    buckets.forEach((rows) => rows.forEach((r) => {
        if (r && r.cycle_ts) seen.add(r.cycle_ts);
    }));
    return Array.from(seen).sort((a, b) => a - b);
}

function pad(n) { return String(n).padStart(2, '0'); }

export function render(history) {
    const ticksEl = document.getElementById('cycle-ticks');
    if (!ticksEl) return;

    const cycles = collectCycles(history);
    if (!cadence.latestCycleTs && cycles.length) {
        setCadence(null, cycles);
    }

    const present = new Set(cycles);
    const interval = cadence.pollIntervalS || DEFAULT_INTERVAL_S;
    const newest = cadence.latestCycleTs;

    if (!newest) {
        ticksEl.innerHTML = '';
        setSummary('Waiting for the first poll.');
        return;
    }

    // Walk back from the newest observed cycle in whole intervals. Anything we
    // cannot find in the history stays hollow — a gap is shown, never filled in.
    const expected = [];
    for (let i = TICK_COUNT - 1; i >= 0; i--) expected.push(newest - i * interval);

    let landed = 0;
    let repaired = 0;
    ticksEl.innerHTML = expected.map((ts) => {
        const isPresent = present.has(ts);
        const isRepaired = repairedCycles.has(ts);
        if (isPresent && !isRepaired) landed++;
        if (isRepaired) repaired++;
        const cls = !isPresent ? 'cycle-tick missing'
            : isRepaired ? 'cycle-tick repaired'
            : 'cycle-tick';
        const when = new Date(ts * 1000);
        const label = !isPresent ? 'no data'
            : isRepaired ? 'carried forward' : 'recorded';
        return `<span class="${cls}" title="${pad(when.getHours())}:${pad(when.getMinutes())} — ${label}"></span>`;
    }).join('');

    const missing = TICK_COUNT - landed - repaired;
    const parts = [`${landed} of the last ${TICK_COUNT} cycles recorded`];
    if (repaired) parts.push(`${repaired} carried forward`);
    if (missing) parts.push(`${missing} missing`);
    setSummary(parts.join(', ') + '.');

    startCountdown();
}

function setSummary(text) {
    const el = document.getElementById('cycle-summary');
    if (el) el.textContent = text;
}

/** Counts down to the next expected write. Shows "due now" rather than a
 *  negative number once that moment passes — the poll may simply be in flight. */
function startCountdown() {
    const el = document.getElementById('cycle-countdown');
    if (!el) return;
    if (countdownTimer) clearInterval(countdownTimer);

    const tick = () => {
        if (!cadence.nextCycleTs) { el.textContent = ''; return; }
        const remaining = Math.round(cadence.nextCycleTs - Date.now() / 1000);
        if (remaining <= 0) {
            el.textContent = 'next poll due';
            el.classList.add('due');
            return;
        }
        el.classList.remove('due');
        el.textContent = `next poll ${pad(Math.floor(remaining / 60))}:${pad(remaining % 60)}`;
    };
    tick();
    countdownTimer = setInterval(tick, 1000);
}

export function stopCountdown() {
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}
