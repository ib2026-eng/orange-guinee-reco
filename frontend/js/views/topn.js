import { topN } from '../api.js';
import { renderClientBadge, renderLoading, renderError } from '../render-helpers.js';

let currentClientId = null;

async function render() {
  const panel = document.getElementById('topnPanel');
  if (!currentClientId) return;
  const n = Math.min(20, Math.max(1, parseInt(document.getElementById('topnInput').value, 10) || 5));
  renderLoading(panel);
  try {
    const data = await topN(currentClientId, n);
    renderClientBadge(currentClientId, data.cold_start);
    if (data.recommendations.length === 0) {
      panel.innerHTML = `<div class="empty-state">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    panel.innerHTML = `
      <table class="reco-table">
        <thead><tr><th>#</th><th>Pass</th><th>Score</th></tr></thead>
        <tbody>
          ${data.recommendations.map((r, i) => `
            <tr>
              <td class="rank">${i + 1}</td>
              <td>${r.nom_pass_regroupe}</td>
              <td class="mono">${r.score !== null && r.score !== undefined ? r.score.toFixed(3) : '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initTopn() {
  document.addEventListener('client:selected', (e) => { currentClientId = e.detail.clientId; render(); });
  document.getElementById('topnInput').addEventListener('change', render);
}
