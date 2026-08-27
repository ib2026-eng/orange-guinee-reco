import { similarClients } from '../api.js';
import { renderClientBadge, renderLoading, renderError } from '../render-helpers.js';

async function render(clientId) {
  const panel = document.getElementById('similarPanel');
  renderLoading(panel);
  try {
    const data = await similarClients(clientId, 5);
    renderClientBadge(clientId, data.cold_start);
    if (data.note) {
      panel.innerHTML = `<div class="empty-state">${data.note}<br><span style="font-size:11.5px;">Repli sur la popularité par segment ci-dessous.</span></div>` +
        (data.recommendations.length ? renderTable(data.recommendations) : '');
      return;
    }
    if (data.recommendations.length === 0) {
      panel.innerHTML = `<div class="empty-state">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    panel.innerHTML = renderTable(data.recommendations);
  } catch (e) {
    renderError(panel, e.message);
  }
}

function renderTable(recommendations) {
  return `
    <table class="reco-table">
      <thead><tr><th>#</th><th>Pass</th><th>Score de similarité</th></tr></thead>
      <tbody>
        ${recommendations.map((r, i) => `
          <tr>
            <td class="rank">${i + 1}</td>
            <td>${r.nom_pass_regroupe}</td>
            <td class="mono">${r.score !== null && r.score !== undefined ? r.score.toFixed(3) : '—'}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

export function initSimilar() {
  document.addEventListener('client:selected', (e) => render(e.detail.clientId));
}
