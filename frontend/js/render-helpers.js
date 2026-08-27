export function renderClientBadge(clientId, coldStart) {
  const row = document.getElementById('clientBadgeRow');
  row.style.display = '';
  row.innerHTML = `
    <span class="cid">Client :</span>
    <span class="badge mono" style="font-family:'JetBrains Mono',monospace;">${clientId}</span>
    <span class="badge ${coldStart ? 'cold-start' : 'actif'}">${coldStart ? 'Cold-start · repli popularité' : 'Client actif'}</span>
  `;
}

export function renderLoading(panel) {
  panel.innerHTML = `<div class="loading-state">Chargement…</div>`;
}

export function renderError(panel, message) {
  panel.innerHTML = `<div class="error-state">${message}</div>`;
}

export function formatGnf(value) {
  if (value === null || value === undefined) return '—';
  return Math.round(value).toLocaleString('fr-FR') + ' GNF';
}

export function formatPct(value) {
  if (value === null || value === undefined) return '—';
  return (value * 100).toFixed(1) + '%';
}
