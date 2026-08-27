import { nextBestOffer } from '../api.js';
import { renderClientBadge, renderLoading, renderError } from '../render-helpers.js';

async function render(clientId) {
  const panel = document.getElementById('nboPanel');
  renderLoading(panel);
  try {
    const data = await nextBestOffer(clientId);
    renderClientBadge(clientId, data.cold_start);
    const reco = data.recommendations[0];
    if (!reco) {
      panel.innerHTML = `<div class="state empty">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    panel.innerHTML = `
      <span class="card-eyebrow">Recommandation</span>
      <div class="hero-pick" style="margin-top:14px;">
        <div class="name">${reco.nom_pass_regroupe}</div>
        <div class="score-tag">${reco.score !== null && reco.score !== undefined ? `score ${reco.score.toFixed(3)}` : 'popularité segment'}</div>
      </div>
    `;
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initNbo() {
  document.addEventListener('client:selected', (e) => render(e.detail.clientId));
}
