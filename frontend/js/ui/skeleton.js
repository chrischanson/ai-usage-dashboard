export function setCard(id, val, label) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.remove('skeleton', 'skeleton-text');
        if (label) {
            el.innerHTML = `<span class="card-label">${label}</span>${val}`;
        } else {
            el.textContent = val;
        }
    }
}

export function showLoadingSkeleton() {
    document.querySelectorAll('.skeleton').forEach(el => {
        el.style.display = '';
    });
}

export function hideAllSkeletons() {
    document.querySelectorAll('.skeleton').forEach(el => {
        el.style.display = 'none';
    });
}

export function renderEmptyState(target) {
    if (target === 'overview') {
        setCard('total-sessions', '--');
        setCard('total-messages', '--');
        setCard('input-tokens', '--');
        setCard('output-tokens', '--');
        setCard('cache-reads', '--');
        setCard('total-cost', '--');
    } else if (target === 'models') {
        const tbody = document.getElementById('models-tbody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state"><div class="empty-state-icon">&#128202;</div><p>No data collected yet. Polling runs every 10 minutes.</p></td></tr>';
        }
        setCard('total-cost', '--');
    }
}
