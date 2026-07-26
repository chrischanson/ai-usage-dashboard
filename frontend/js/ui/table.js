import { state } from '../state.js';
import { formatNum, formatCost, formatModelName, escapeHtml } from '../format.js';
import { COLORS } from '../colors.js';
import { setCard, renderEmptyState } from './skeleton.js';
import { computeModelsFromHistory } from '../derive.js';
import { renderModelChart, charts } from '../charts.js';

export function renderModels(models) {
    const tbody = document.getElementById('models-tbody');
    if (!tbody) return;
    if (!models || !models.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><div class="empty-state-icon">&#128202;</div><p>No model usage data available.</p></td></tr>';
        setCard('total-cost', '--');
        return;
    }

    const totalCost = models.reduce((sum, m) => sum + (m.cost || 0), 0);
    setCard('total-cost', formatCost(totalCost));

    // The dot carries the row's SOURCE identity, matching its badge and the
    // donut. It must never be assigned by row rank: sorting the table would
    // otherwise repaint every model a different colour.
    const dotFor = (m) => (m.source && COLORS[m.source])
        ? COLORS[m.source].accent
        : COLORS[state.currentSource].accent;
    const grandTotal = models.reduce((sum, m) => sum + (m.input_tokens || 0) + (m.output_tokens || 0), 0);

    const rows = models.map((m, i) => {
        const input = m.input_tokens || 0;
        const output = m.output_tokens || 0;
        const total = input + output;
        const pct = grandTotal > 0 ? (total / grandTotal * 100) : 0;
        const cost = m.cost;
        const color = dotFor(m);
        const name = formatModelName(m.model_name, m.source);
        const badgeHtml = m.source ? `<span class="badge badge-${m.source}">${escapeHtml(m.source)}</span>` : '';
        return {
            model_name: name,
            displayName: name,
            badge: badgeHtml,
            color: color,
            input_tokens: input,
            output_tokens: output,
            total: total,
            pct: pct,
            cost: cost,
            messages: m.messages || 0,
        };
    });

    state.cachedModelData = rows;
    renderSortedModels();
}

export function renderSortedModels() {
    const tbody = document.getElementById('models-tbody');
    if (!tbody || !state.cachedModelData) return;

    const sorted = [...state.cachedModelData].sort((a, b) => {
        let av, bv;
        if (state.sortColumn === 'model_name') {
            av = a.model_name.toLowerCase();
            bv = b.model_name.toLowerCase();
            if (av < bv) return state.sortDirection === 'asc' ? -1 : 1;
            if (av > bv) return state.sortDirection === 'asc' ? 1 : -1;
            return 0;
        }
        av = a[state.sortColumn] || 0;
        bv = b[state.sortColumn] || 0;
        return state.sortDirection === 'asc' ? av - bv : bv - av;
    });

    tbody.innerHTML = sorted.map(m => {
        const costDisplay = formatCost(m.cost);
        const costClass = (m.cost == null || m.cost === 0) ? 'model-cost muted' : 'model-cost';
        return `<tr>
            <td><div class="model-name"><span class="model-color-dot" style="background:${m.color}"></span>${escapeHtml(m.model_name)}${m.badge}</div></td>
            <td>${formatNum(m.input_tokens)}</td>
            <td>${formatNum(m.output_tokens)}</td>
            <td>${formatNum(m.total)}</td>
            <td>${m.pct.toFixed(1)}%</td>
            <td class="${costClass}">${costDisplay}</td>
        </tr>`;
    }).join('');

    // Render mobile card view (same sorted data)
    renderModelCards(sorted);

    document.querySelectorAll('#models-table th.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === state.sortColumn) {
            th.classList.add(state.sortDirection === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });
}

function renderModelCards(sorted) {
    // Find or create the cards container
    let cardsContainer = document.getElementById('models-cards');
    if (!cardsContainer) {
        const modelsList = document.querySelector('.models-list');
        if (!modelsList) return;
        cardsContainer = document.createElement('div');
        cardsContainer.id = 'models-cards';
        cardsContainer.className = 'models-cards';
        modelsList.appendChild(cardsContainer);
    }

    cardsContainer.innerHTML = sorted.map(m => {
        const costDisplay = formatCost(m.cost);
        const costClass = (m.cost == null || m.cost === 0) ? 'card-figure-value muted' : 'card-figure-value';
        return `<div class="model-card">
            <div class="card-header">
                <div class="model-name">
                    <span class="model-color-dot" style="background:${m.color}"></span>
                    ${escapeHtml(m.model_name)}
                </div>
                ${m.badge}
            </div>
            <div class="card-figures">
                <div class="card-figure">
                    <div class="card-figure-label">Input</div>
                    <div class="card-figure-value">${formatNum(m.input_tokens)}</div>
                </div>
                <div class="card-figure">
                    <div class="card-figure-label">Output</div>
                    <div class="card-figure-value">${formatNum(m.output_tokens)}</div>
                </div>
                <div class="card-figure">
                    <div class="card-figure-label">Total</div>
                    <div class="card-figure-value">${formatNum(m.total)}</div>
                </div>
                <div class="card-figure">
                    <div class="card-figure-label">%</div>
                    <div class="card-figure-value">${m.pct.toFixed(1)}%</div>
                </div>
                <div class="card-figure">
                    <div class="card-figure-label">Cost</div>
                    <div class="${costClass}">${costDisplay}</div>
                </div>
            </div>
        </div>`;
    }).join('');
}

export async function refreshModels() {

    if (state.timeRange === 'all') {
        if (state.cachedLatestOverview) {
            renderModels(state.cachedLatestOverview.models || []);
            renderModelChart(state.cachedLatestOverview.models || []);
        } else {
            renderEmptyState('models');
            if (charts.modelChartInstance) {
                charts.modelChartInstance.destroy();
                charts.modelChartInstance = null;
            }
        }
    } else if (state.cachedHistory) {
        const isCombined = state.currentSource === 'combined';
        const historyValid = isCombined
            ? (typeof state.cachedHistory === 'object' && !Array.isArray(state.cachedHistory))
            : Array.isArray(state.cachedHistory);
        if (historyValid) {
            const models = computeModelsFromHistory(state.cachedHistory, state.timeRange);
            if (models && models.length > 0) {
                renderModels(models);
                renderModelChart(models);
            } else {
                renderEmptyState('models');
                if (charts.modelChartInstance) {
                    charts.modelChartInstance.destroy();
                    charts.modelChartInstance = null;
                }
            }
        }
    }
}
