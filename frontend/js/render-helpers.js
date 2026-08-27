export function renderClientBadge(clientId, coldStart) {
  const row = document.getElementById('clientBadgeRow');
  row.style.display = '';
  row.innerHTML = `
    <span class="cid">${clientId}</span>
    <span class="pill ${coldStart ? 'cold' : 'actif'}">${coldStart ? 'Cold-start · repli popularité' : 'Client actif'}</span>
  `;
}

export function renderLoading(panel) {
  panel.innerHTML = `<div class="state loading">Chargement…</div>`;
}

export function renderError(panel, message) {
  panel.innerHTML = `<div class="state-error">${message}</div>`;
}

export function formatGnf(value) {
  if (value === null || value === undefined) return '—';
  return Math.round(value).toLocaleString('fr-FR') + ' GNF';
}

export function formatPct(value) {
  if (value === null || value === undefined) return '—';
  return (value * 100).toFixed(1) + '%';
}
