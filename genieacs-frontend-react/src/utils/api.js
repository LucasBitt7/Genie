// src/utils/api.js

/**
 * Lê o BASE URL do backend do ACS de localStorage.
 * Fallback: http://localhost:8000
 */
export function getBackendUrl() {
  return localStorage.getItem('genieacs_backend_url') || 'http://localhost:8000';
}

/**
 * Envia requisição ao backend FastAPI.
 * - method: 'POST' | 'GET' | ...
 * - path: ex. '/devices/<id>/wifi'
 * - options.query: objeto de querystring (ex. { connection_request: true })
 * - options.body: objeto JSON (ex. { ssid, password })
 * - options.apiKey: opcional; se não vier, pegamos do localStorage
 */
export async function sendRequest(method, path, { query = {}, body, apiKey } = {}) {
  const baseUrl = getBackendUrl();
  const qs = new URLSearchParams(
    Object.entries(query).flatMap(([k, v]) => v === undefined || v === null ? [] : [[k, String(v)]])
  ).toString();
  const url = `${baseUrl}${path}${qs ? `?${qs}` : ''}`;

  const headers = { 'Content-Type': 'application/json' };
  const key = apiKey || localStorage.getItem('genieacs_api_key');
  if (key) headers['X-API-Key'] = key;

  const resp = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    const text = await resp.text().catch(() => '');
    throw new Error(text || `HTTP ${resp.status}`);
  }
  return resp.json();
}
