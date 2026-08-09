import { formatCost, clampPct, escapeHtml } from '../format.js';

export function renderMeterRow(label, valueText, pct, barColor, refreshStr) {
    const titleAttr = refreshStr ? ` title="${escapeHtml(refreshStr)}"` : '';
    // The reset time rides on the value line instead of taking a third line of
    // its own — with ten meters on screen that alone cost ~140px of height.
    const shortRefresh = refreshStr
        ? String(refreshStr).replace(/^(Refreshes|Resets)\s+in\s+/i, '')
        : '';
    const refreshLine = shortRefresh
        ? `<span class="quota-refresh">${escapeHtml(shortRefresh)}</span>`
        : '';

    // Map old color names to new status classes
    const colorMap = { 'green': 'ok', 'amber': 'warn', 'red': 'danger' };
    const statusClass = colorMap[barColor] || 'ok';

    // Calculate filled tick count: 24 ticks total, filled = round(pct/100 * 24), clamped to 0..24
    const filledCount = Math.max(0, Math.min(24, Math.round(pct / 100 * 24)));

    // Build meter ticks HTML
    let ticksHtml = '';
    for (let i = 0; i < 24; i++) {
        if (i < filledCount) {
            // Filled tick: use status class, or danger if at/past 90% (index >= 21)
            const tickClass = i >= 21 ? 'danger' : statusClass;
            ticksHtml += `<span class="meter-tick filled ${tickClass}"></span>`;
        } else {
            // Unfilled tick
            ticksHtml += `<span class="meter-tick"></span>`;
        }
    }

    return `
        <div class="quota-limit">
            <div class="quota-limit-header">
                <span class="quota-limit-label">${escapeHtml(label)}</span>
                <span class="quota-limit-value">${valueText}${refreshLine}</span>
            </div>
            <div class="quota-meter" role="meter" aria-valuenow="${Math.round(pct)}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHtml(label)}"${titleAttr}>
                ${ticksHtml}
            </div>
        </div>
    `;
}

export function renderQuota(data, source) {
    const container = document.getElementById('quota-cards');
    const titleEl = document.getElementById('quota-title');

    container.className = 'quota-cards source-' + source;
    container.innerHTML = '';
    if (!data || Object.keys(data).length === 0) {
        container.innerHTML = '<div class="empty-state"><p>No quota details available.</p></div>';
        return;
    }

    // OpenCode and Codex are both one-line cards -- side by side with a
    // multi-meter card, the grid stretches them to match its height and
    // they end up half-empty. Stack the two of them in a shared column
    // instead, so the column's total height is comparable to a full card.
    let compactColumn = null;
    function getCompactColumn() {
        if (!compactColumn) {
            compactColumn = document.createElement('div');
            compactColumn.className = 'quota-column';
            container.appendChild(compactColumn);
        }
        return compactColumn;
    }

    for (const [src, quotaData] of Object.entries(data)) {
        if (!quotaData || Object.keys(quotaData).length === 0) continue;

        if (src === 'opencode') {
            const group = quotaData.opencode;
            if (group) {
                const cost = group.total_cost || {};
                renderOpenCodeCost(getCompactColumn(), cost);
            }
        } else if (src === 'codex') {
            const group = quotaData.openai;
            if (group) {
                const rateLimit = group.rate_limit || {};
                const plan = quotaData._plan || 'free';
                const targetContainer = getCompactColumn();
                renderCodexQuota(targetContainer, rateLimit, plan);
            }
        } else if (src === 'claude') {
            const inCompactColumn = (source === 'combined' || source === 'all');
            const targetContainer = inCompactColumn ? getCompactColumn() : container;
            renderClaudeQuota(targetContainer, quotaData, inCompactColumn);
        } else if (src === 'agy') {
            renderAgyQuota(container, quotaData);
        } else {
            const agyPlan = quotaData._plan || 'Free';
            for (const [group, limits] of Object.entries(quotaData)) {
                if (group === '_plan') continue;
                const card = document.createElement('div');
                card.className = 'quota-group';
                const groupLabel = group.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\bGpt\b/g, 'GPT');
                let limitsHtml = '';
                for (const [limitType, info] of Object.entries(limits)) {
                    const label = limitType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                    const pct = clampPct(info.remaining_pct);
                    const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
                    const seconds = info.refreshes_in_seconds || info.refreshes_in || 0;
                    let refreshStr = '';
                    if (seconds > 0) {
                        if (seconds < 3600) {
                            refreshStr = `Refreshes in ${Math.round(seconds / 60)} min`;
                        } else {
                            refreshStr = `Refreshes in ${Math.round(seconds / 3600)} hr`;
                        }
                    }
                    limitsHtml += renderMeterRow(label, `${pct.toFixed(1)}%`, pct, barColor, refreshStr);
                }
                const planBadge = src === 'agy' ? ` <span class="badge badge-agy">${escapeHtml(agyPlan)}</span>` : '';
                card.innerHTML = `<h3>${escapeHtml(groupLabel)}${planBadge}</h3>${limitsHtml}`;
                container.appendChild(card);
            }
        }
    }
}

export function renderAgyQuota(container, data) {
    const agyPlan = data._plan || 'Gemini Code Assist';

    const card = document.createElement('div');
    card.className = 'quota-group';

    const groupKeys = Object.keys(data).filter(k => k !== '_plan');
    groupKeys.sort((a, b) => {
        if (a.includes('gemini')) return -1;
        if (b.includes('gemini')) return 1;
        return 0;
    });

    let sectionsHtml = '';
    let isFirstSection = true;

    for (const groupKey of groupKeys) {
        const limits = data[groupKey];
        if (!limits || typeof limits !== 'object') continue;

        let subTitle = '';
        if (groupKey === 'gemini_models') {
            subTitle = 'Gemini';
        } else if (groupKey === 'claude_gpt_models') {
            subTitle = 'Claude / GPT';
        } else {
            subTitle = groupKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\bGpt\b/g, 'GPT');
        }

        let limitsHtml = '';

        // Session (5h) limit — top
        const fiveHour = limits.five_hour_limit || limits['5h'] || limits.five_hour || {};
        if (fiveHour.used !== undefined || fiveHour.remaining_pct !== undefined) {
            const pct = clampPct(fiveHour.remaining_pct);
            const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
            const seconds = fiveHour.refreshes_in_seconds || fiveHour.refreshes_in || 0;
            let refreshStr = '';
            if (seconds > 0) {
                if (seconds < 3600) {
                    refreshStr = `Refreshes in ${Math.round(seconds / 60)} min`;
                } else {
                    refreshStr = `Refreshes in ${Math.round(seconds / 3600)} hr`;
                }
            }
            limitsHtml += renderMeterRow('Session (5h)', `${pct.toFixed(1)}%`, pct, barColor, refreshStr);
        }

        // Weekly limit — bottom
        const weekly = limits.weekly_limit || limits.weekly || {};
        if (weekly.used !== undefined || weekly.remaining_pct !== undefined) {
            const pct = clampPct(weekly.remaining_pct);
            const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
            const seconds = weekly.refreshes_in_seconds || weekly.refreshes_in || 0;
            let refreshStr = '';
            if (seconds > 0) {
                if (seconds >= 86400) {
                    refreshStr = `Refreshes in ${Math.round(seconds / 86400)} days`;
                } else if (seconds >= 3600) {
                    refreshStr = `Refreshes in ${Math.round(seconds / 3600)} hr`;
                } else {
                    refreshStr = `Refreshes in ${Math.round(seconds / 60)} min`;
                }
            }
            limitsHtml += renderMeterRow('Weekly', `${pct.toFixed(1)}%`, pct, barColor, refreshStr);
        }

        for (const [limitType, info] of Object.entries(limits)) {
            if (['five_hour_limit', '5h', 'five_hour', 'weekly_limit', 'weekly'].includes(limitType)) continue;
            if (!info || typeof info !== 'object' || info.remaining_pct === undefined) continue;
            const pct = clampPct(info.remaining_pct);
            const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
            const label = limitType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            limitsHtml += renderMeterRow(label, `${pct.toFixed(1)}%`, pct, barColor, '');
        }

        const dividerClass = isFirstSection ? '' : ' quota-section-divider';
        sectionsHtml += `
            <div class="quota-section${dividerClass}">
                <div class="quota-subtitle">${escapeHtml(subTitle)}</div>
                ${limitsHtml}
            </div>
        `;
        isFirstSection = false;
    }

    const planBadge = ` <span class="badge badge-agy">${escapeHtml(agyPlan)}</span>`;
    card.innerHTML = `<h3>Antigravity${planBadge}</h3>${sectionsHtml}`;
    container.appendChild(card);
}

export function renderOpenCodeCost(container, cost) {
    const spent = cost.used || 0;
    const card = document.createElement('div');
    card.className = 'quota-group';
    card.innerHTML = `
        <h3>OpenCode <span class="badge badge-opencode">Free Tier</span></h3>
        <div class="quota-limit">
            <div class="quota-limit-header">
                 <span class="quota-limit-label">Total Cost</span>
                 <span class="quota-limit-value">$${spent.toFixed(2)}</span>
            </div>
        </div>
    `;
    container.appendChild(card);
}

// OpenAI reports plan_type as a squashed enum ("chatgptplusplan"). Blindly
// title-casing it and appending " Plan" produced "Chatgptplusplan Plan".
// These are display names for a known enum, not guesses about the data.
const CODEX_PLAN_LABELS = {
    chatgptplusplan: 'ChatGPT Plus',
    chatgptproplan: 'ChatGPT Pro',
    chatgptteamplan: 'ChatGPT Team',
    chatgptenterpriseplan: 'ChatGPT Enterprise',
    free: 'Free',
};

function formatCodexPlan(planType) {
    const raw = String(planType || 'free').trim();
    const known = CODEX_PLAN_LABELS[raw.toLowerCase()];
    if (known) return known;
    // Unknown value: show it as reported rather than inventing a tier, and
    // don't tack on a second "Plan" when it already ends in one.
    const titled = raw.charAt(0).toUpperCase() + raw.slice(1);
    return /plan$/i.test(raw) ? titled : titled + ' Plan';
}

export function renderCodexQuota(container, rateLimit, planType) {
    const card = document.createElement('div');
    card.className = 'quota-group';

    const planLabel = formatCodexPlan(planType);
    const hasLimit = rateLimit.remaining_pct !== undefined;

    if (hasLimit) {
        const pct = clampPct(rateLimit.remaining_pct);
        const barColor = pct > 50 ? 'green' : pct > 20 ? 'amber' : 'red';
        const resetAt = rateLimit.reset_at;
        let seconds = rateLimit.refreshes_in || rateLimit.refreshes_in_seconds || 0;
        if (resetAt && resetAt > 0) {
            const nowSec = Math.floor(Date.now() / 1000);
            seconds = Math.max(0, Math.floor(resetAt - nowSec));
        }

        let refreshStr = '';
        if (seconds > 0) {
            const days = Math.floor(seconds / 86400);
            const hrs = Math.floor((seconds % 86400) / 3600);
            const mins = Math.floor((seconds % 3600) / 60);

            let timeStr = '';
            if (days > 0) {
                timeStr = `${days}d ${hrs}h`;
            } else if (hrs > 0) {
                timeStr = `${hrs}h ${mins}m`;
            } else {
                timeStr = `${mins}m`;
            }

            if (resetAt && resetAt > 0) {
                const dt = new Date(resetAt * 1000);
                const formatted = dt.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                refreshStr = `Resets in ${timeStr} (${formatted})`;
            } else {
                refreshStr = `Resets in ${timeStr}`;
            }
        } else if (pct >= 99.9) {
            refreshStr = 'Quota reset (100% available)';
        }

        let windowLabel = 'Primary Limit';
        if (rateLimit.window_minutes) {
            const wm = rateLimit.window_minutes;
            if (wm >= 43200) windowLabel = 'Primary Limit (Monthly)';
            else if (wm >= 10080) windowLabel = 'Primary Limit (Weekly)';
            else if (wm >= 1440) windowLabel = 'Primary Limit (Daily)';
            else if (wm >= 60) windowLabel = `Primary Limit (${Math.round(wm / 60)}h window)`;
            else windowLabel = `Primary Limit (${wm}m window)`;
        }

        card.innerHTML = `
            <h3>Codex <span class="badge badge-codex">${escapeHtml(planLabel)}</span></h3>
            ${renderMeterRow(windowLabel, `${pct.toFixed(1)}% remaining`, pct, barColor, refreshStr)}
        `;
    } else {
        card.innerHTML = `
            <h3>Codex <span class="badge badge-codex">${escapeHtml(planLabel)}</span></h3>
            <div class="quota-limit">
                <p style="color: #8a9fc8; font-size: 0.85rem; margin: 0.5rem 0;">
                    Rate limit details will populate once Codex activity is recorded.
                </p>
            </div>
        `;
    }
    container.appendChild(card);
}

export function renderClaudeQuota(container, data, wide) {
    const card = document.createElement('div');
    card.className = wide ? 'quota-group quota-group--wide' : 'quota-group';

    const plan = data._plan || 'Claude Pro';

    let limitsHtml = '';

    // Session (5h) limit — shown first (matches AGY order)
    const sessionGroup = data.session || {};
    const sessionLimit = sessionGroup.five_hour || {};
    if (sessionLimit.used !== undefined) {
        const remaining = clampPct(sessionLimit.remaining_pct);
        const barColor = remaining > 50 ? 'green' : remaining > 20 ? 'amber' : 'red';
        const seconds = sessionLimit.refreshes_in_seconds || 0;
        let refreshStr = '';
        if (seconds > 0) {
            if (seconds < 3600) {
                refreshStr = `Resets in ${Math.round(seconds / 60)} min`;
            } else {
                refreshStr = `Resets in ${Math.round(seconds / 3600)} hr`;
            }
        }
        limitsHtml += renderMeterRow('Session (5h)', `${remaining.toFixed(1)}% left`, remaining, barColor, refreshStr);
    }

    // Weekly limit
    const weeklyGroup = data.weekly || {};
    const weeklyAll = weeklyGroup.all_models || {};
    if (weeklyAll.used !== undefined) {
        const remaining = clampPct(weeklyAll.remaining_pct);
        const barColor = remaining > 50 ? 'green' : remaining > 20 ? 'amber' : 'red';
        const seconds = weeklyAll.refreshes_in_seconds || 0;
        let refreshStr = '';
        if (seconds > 0) {
            if (seconds >= 86400) {
                refreshStr = `Resets in ${Math.round(seconds / 86400)} days`;
            } else if (seconds >= 3600) {
                refreshStr = `Resets in ${Math.round(seconds / 3600)} hr`;
            } else {
                refreshStr = `Resets in ${Math.round(seconds / 60)} min`;
            }
        }
        limitsHtml += renderMeterRow('Weekly (All Models)', `${remaining.toFixed(1)}% left`, remaining, barColor, refreshStr);
    }

    // Per-model weekly limits
    for (const [modelName, info] of Object.entries(weeklyGroup)) {
        if (modelName === 'all_models' || !info || typeof info !== 'object') continue;
        if (info.used === undefined) continue;
        const remaining = clampPct(info.remaining_pct);
        const barColor = remaining > 50 ? 'green' : remaining > 20 ? 'amber' : 'red';
        limitsHtml += renderMeterRow(`Weekly: ${modelName}`, `${remaining.toFixed(1)}% left`, remaining, barColor, '');
    }

    card.innerHTML = `
        <h3>Claude <span class="badge badge-claude">${escapeHtml(plan)}</span></h3>
        ${limitsHtml || '<p style="color: #8a9fc8; font-size: 0.85rem; margin: 0.5rem 0;">Claude quota data will appear once authenticated.</p>'}
    `;
    container.appendChild(card);
}
