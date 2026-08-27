import { hybridRoi } from '../api.js';
import { renderClientBadge, renderLoading, renderError, formatGnf, formatPct } from '../render-helpers.js';

async function render(clientId) {
  const panel = document.getElementById('hybridPanel');
  renderLoading(panel);
  try {
    const data = await hybridRoi(clientId, 5);
    renderClientBadge(clientId, data.cold_start);
    if (data.recommendations.length === 0) {
      panel.innerHTML = `<div class="empty-state">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    if (data.cold_start) {
      panel.innerHTML = `
        <table class="reco-table">
          <thead><tr><th>#</th><th>Pass</th><th>Source</th></tr></thead>
          <tbody>
            ${data.recommendations.map((r, i) => `
              <tr><td class="rank">${i + 1}</td><td>${r.nom_pass_regroupe}</td><td class="mono">${r.source ?? '—'}</td></tr>
            `).join('')}
          </tbody>
        </table>
      `;
      return;
    }
    panel.innerHTML = `
      <table class="reco-table">
        <thead><tr><th>#</th><th>Pass</th><th>P(achat)</th><th>Prix catalogue</th><th>Valeur attendue</th></tr></thead>
        <tbody>
          ${data.recommendations.map((r, i) => `
            <tr>
              <td class="rank">${i + 1}</td>
              <td>${r.nom_pass_regroupe}</td>
              <td class="mono">${formatPct(r.proba_achat)}</td>
              <td class="mono">${formatGnf(r.prix_catalogue)}</td>
              <td class="expected-value">${formatGnf(r.valeur_attendue)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initHybrid() {
  document.addEventListener('client:selected', (e) => render(e.detail.clientId));
}
