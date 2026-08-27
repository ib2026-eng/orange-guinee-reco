import { similarClients } from '../api.js';
import { renderClientBadge, renderLoading, renderError } from '../render-helpers.js';

function renderList(recommendations) {
  return `<div class="reco-list">` + recommendations.map((r, i) => `
    <div class="reco-row">
      <div class="rank">${i + 1}</div>
      <div class="name">${r.nom_pass_regroupe}</div>
      <div class="meta">${r.score !== null && r.score !== undefined ? r.score.toFixed(3) : '—'}</div>
    </div>
  `).join('') + `</div>`;
}

async function render(clientId) {
  const panel = document.getElementById('similarPanel');
  renderLoading(panel);
  try {
    const data = await similarClients(clientId, 5);
    renderClientBadge(clientId, data.cold_start);
    if (data.recommendations.length === 0) {
      panel.innerHTML = `<div class="state empty">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    const note = data.note
      ? `<div class="state empty" style="padding:0 0 16px; text-align:left;">${data.note} — repli sur la popularité par segment ci-dessous.</div>`
      : '';
    panel.innerHTML = `<span class="card-eyebrow">Recommandations collaboratives</span><div style="margin-top:14px;">${note}${renderList(data.recommendations)}</div>`;
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initSimilar() {
  document.addEventListener('client:selected', (e) => render(e.detail.clientId));
}
