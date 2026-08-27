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
      panel.innerHTML = `<div class="empty-state">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    panel.innerHTML = `
      <span class="panel-label">RECOMMANDATION</span>
      <div style="display:flex; align-items:baseline; gap:16px;">
        <div style="font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:32px;">${reco.nom_pass_regroupe}</div>
        ${reco.score !== null && reco.score !== undefined
          ? `<div style="font-family:'JetBrains Mono',monospace; color:var(--grey); font-size:13px;">score ${reco.score.toFixed(3)}</div>`
          : `<div style="font-family:'JetBrains Mono',monospace; color:var(--grey); font-size:13px;">popularité segment</div>`}
      </div>
    `;
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initNbo() {
  document.addEventListener('client:selected', (e) => render(e.detail.clientId));
}
