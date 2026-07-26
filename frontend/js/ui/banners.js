// Error banner
const errorBanner = document.getElementById('error-banner');
const errorMsg = document.getElementById('error-message');
const retryBtn = document.getElementById('retry-btn');
const dismissBtn = document.getElementById('dismiss-btn');

export function showError(msg) {
    if (!errorBanner || !errorMsg) return;
    errorMsg.textContent = msg;
    errorBanner.hidden = false;
}

export function hideError() {
    if (!errorBanner) return;
    errorBanner.hidden = true;
}

// main.js owns refresh() and already imports this module, so importing it back
// would be a cycle. It registers the handler here at init instead.
let retryHandler = null;

export function setRetryHandler(fn) {
    retryHandler = fn;
}

if (retryBtn) {
    retryBtn.addEventListener('click', () => {
        hideError();
        if (retryHandler) retryHandler();
    });
}
if (dismissBtn) {
    dismissBtn.addEventListener('click', hideError);
}

// Data integrity banner
const integrityBanner = document.getElementById('integrity-banner');
const integrityMsg = document.getElementById('integrity-message');
const integrityDismissBtn = document.getElementById('integrity-dismiss-btn');

export function showIntegrityWarning(warnings) {
    if (!integrityBanner || !integrityMsg || !warnings || !warnings.length) return;
    const extra = warnings.length > 1 ? ` (+${warnings.length - 1} more)` : '';
    integrityMsg.textContent = 'Data integrity: ' + warnings[0] + extra;
    integrityBanner.hidden = false;
}

export function hideIntegrityWarning() {
    if (!integrityBanner) return;
    integrityBanner.hidden = true;
}

if (integrityDismissBtn) {
    integrityDismissBtn.addEventListener('click', () => {
        hideIntegrityWarning();
    });
}

// Status indicator
const statusText = document.getElementById('status-text');
const statusDot = document.querySelector('.dot');
const statusIndicator = document.getElementById('status-indicator');

export function setStatus(type, text) {
    if (!statusText || !statusDot || !statusIndicator) return;
    statusText.textContent = text || 'Live';
    statusText.classList.remove('stale', 'offline');
    statusDot.classList.remove('stale', 'offline');
    statusIndicator.classList.remove('offline');
    if (type === 'stale') {
        statusText.classList.add('stale');
        statusDot.classList.add('stale');
    } else if (type === 'offline') {
        statusText.classList.add('offline');
        statusDot.classList.add('offline');
        statusIndicator.classList.add('offline');
    }
}
