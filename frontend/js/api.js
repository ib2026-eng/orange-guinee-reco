import { API_URL } from './config.js';

async function post(path) {
  const res = await fetch(`${API_URL}${path}`, { method: 'POST' });
  if (res.status === 404) {
    throw new Error('Client inconnu.');
  }
  if (!res.ok) {
    throw new Error(`Erreur API (${res.status})`);
  }
  return res.json();
}

export function nextBestOffer(clientId) {
  return post(`/recommend/next-best-offer/${encodeURIComponent(clientId)}`);
}

export function topN(clientId, n) {
  return post(`/recommend/top-n/${encodeURIComponent(clientId)}?n=${n}`);
}

export function similarClients(clientId, n = 5) {
  return post(`/recommend/similar-clients/${encodeURIComponent(clientId)}?n=${n}`);
}

export function hybridRoi(clientId, n = 5) {
  return post(`/recommend/hybrid-roi/${encodeURIComponent(clientId)}?n=${n}`);
}

export async function health() {
  const res = await fetch(`${API_URL}/health`);
  if (!res.ok) throw new Error('API indisponible');
  return res.json();
}

export async function sampleClients() {
  const res = await fetch(`${API_URL}/demo/sample-clients`);
  if (!res.ok) throw new Error('API indisponible');
  return res.json();
}
