import { initTabs } from './tabs.js';
import { initClientSearch } from './client-search.js';
import { initNbo } from './views/nbo.js';
import { initTopn } from './views/topn.js';
import { initSimilar } from './views/similar.js';
import { initHybrid } from './views/hybrid.js';
import { health } from './api.js';

initTabs();
initClientSearch();
initNbo();
initTopn();
initSimilar();
initHybrid();

async function checkHealth() {
  const badge = document.getElementById('apiStatusBadge');
  try {
    const data = await health();
    badge.textContent = `API · ${data.n_clients.toLocaleString('fr-FR')} clients · ${data.n_pass} pass`;
  } catch {
    badge.textContent = 'API · injoignable';
    badge.style.borderColor = 'rgba(255,60,60,.5)';
  }
}
checkHealth();
