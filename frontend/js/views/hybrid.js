import { hybridRoi } from '../api.js';
import { renderClientBadge, renderLoading, renderError, formatGnf, formatPct } from '../render-helpers.js';

async function render(clientId) {
  const panel = document.getElementById('hybridPanel');
  renderLoading(panel);
  try {
    const data = await hybridRoi(clientId, 5);
    renderClientBadge(clientId, data.cold_start);
    if (data.recommendations.length === 0) {
      panel.innerHTML = `<div class="state empty">Aucune recommandation disponible pour ce client.</div>`;
      return;
    }
    if (data.cold_start) {
      panel.innerHTML = `<span class="card-eyebrow">Repli popularité</span><div class="reco-list" style="margin-top:14px;">` +
        data.recommendations.map((r, i) => `
          <div class="reco-row">
            <div class="rank">${i + 1}</div>
            <div class="name">${r.nom_pass_regroupe}</div>
            <div class="meta">${r.source ?? '—'}</div>
          </div>
        `).join('') + `</div>`;
      return;
    }
    panel.innerHTML = `
      <span class="card-eyebrow">Classement par valeur attendue</span>
      <div style="margin-top:14px;">
        <div class="roi-head"><span></span><span>Pass</span><span>P(achat)</span><span>Prix catalogue</span><span>Valeur attendue</span></div>
        ${data.recommendations.map((r, i) => `
          <div class="roi-row">
            <div class="rank">${i + 1}</div>
            <div class="name">${r.nom_pass_regroupe}</div>
            <div class="num">${formatPct(r.proba_achat)}</div>
            <div class="num">${formatGnf(r.prix_catalogue)}</div>
            <div class="ev">${formatGnf(r.valeur_attendue)}</div>
          </div>
        `).join('')}
      </div>
    `;
  } catch (e) {
    renderError(panel, e.message);
  }
}

export function initHybrid() {
  document.addEventListener('client:selected', (e) => render(e.detail.clientId));
}
