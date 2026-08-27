import { sampleClients } from './api.js';

let currentClientId = null;

export function getCurrentClientId() {
  return currentClientId;
}

function selectClient(clientId) {
  currentClientId = clientId;
  document.getElementById('clientSearchInput').value = clientId;
  document.dispatchEvent(new CustomEvent('client:selected', { detail: { clientId } }));
}

async function renderSampleChips() {
  const el = document.getElementById('clientSamples');
  try {
    const { clients } = await sampleClients();
    el.innerHTML = `<span class="lbl">Exemples :</span>` + clients.map(c =>
      `<button type="button" class="chip ${c.cold_start ? 'cold' : ''}" data-id="${c.client_id}">${c.client_id}${c.cold_start ? ' · cold-start' : ''}</button>`
    ).join('');
    el.querySelectorAll('.chip').forEach(btn => {
      btn.addEventListener('click', () => selectClient(btn.dataset.id));
    });
  } catch {
    el.innerHTML = '';
  }
}

export function initClientSearch() {
  const input = document.getElementById('clientSearchInput');
  const btn = document.getElementById('clientSearchBtn');

  const submit = () => {
    const value = input.value.trim();
    if (value) selectClient(value);
  };

  btn.addEventListener('click', submit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });

  renderSampleChips();
}
