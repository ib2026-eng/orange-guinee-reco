import { topN } from '../api.js';
import { renderClientBadge, renderLoading, renderError } from '../render-helpers.js';

let currentClientId = null;

function renderList(recommendations) {
  return `<div class="reco-list">` + recommendations.map((r, i) => `
    <div class="reco-row">
      <div class="rank">${i + 1}</div>
      <div class="name">${r.nom_pass_regroupe}</div>
      <div class="meta">${r.score !== null && r.score !== undefined ? r.score.toFixed(3) : '—'}</div>
    </div>
  `).join('') + `</div>`;
}

async function render() {
  const panel = document.getElementById('topnPanel');
  if (!currentClientId) return;
  const n = Math.min(20, Math.max(1, parseInt(document.getElementById('topnInput').value, 10) || 5));
  renderLoading(panel);
  try {
    const data = await topN(currentClientId, n);
    renderClientBadge(currentClientId, data.cold_start);
    if (data.recommendations.length === 0) {
      panel.innerHTML = `<div class="state empty">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    panel.innerHTML = renderList(data.recommendations);
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initTopn() {
  document.addEventListener('client:selected', (e) => { currentClientId = e.detail.clientId; render(); });
  document.getElementById('topnInput').addEventListener('change', render);
}
