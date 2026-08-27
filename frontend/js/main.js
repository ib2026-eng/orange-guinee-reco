import { initNav } from './nav.js';
import { initClientSearch } from './client-search.js';
import { initNbo } from './views/nbo.js';
import { initTopn } from './views/topn.js';
import { initSimilar } from './views/similar.js';
import { initHybrid } from './views/hybrid.js';
import { health } from './api.js';

initNav();
initClientSearch();
initNbo();
initTopn();
initSimilar();
initHybrid();

async function checkHealth() {
  const badge = document.getElementById('apiStatusBadge');
  const dot = document.getElementById('apiPulseDot');
  try {
    const data = await health();
    badge.lastChild.textContent = `${data.n_clients.toLocaleString('fr-FR')} clients · ${data.n_pass} pass`;
    dot.classList.remove('off');
  } catch {
    badge.lastChild.textContent = 'API injoignable';
    dot.classList.add('off');
  }
}
checkHealth();
