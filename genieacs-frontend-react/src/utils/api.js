// src/utils/api.js
//
// Utilitários para o frontend (HTTP + SSE) compatível com seu sendRequest antigo.

export function getBackendUrl() {
  return localStorage.getItem('genieacs_backend_url') || 'http://localhost:8000';
}

function getDefaultApiKey() {
  return localStorage.getItem('genieacs_api_key') || '';
}

function toQueryString(obj = {}) {
  const entries = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null) continue;
    if (typeof v === 'string' && v.trim() === '') continue;
    if (typeof v === 'boolean') entries.push([k, v ? 'true' : 'false']);
    else entries.push([k, String(v)]);
  }
  return new URLSearchParams(entries).toString();
}

async function getJSON(pathWithQuery, apiKey) {
  const base = getBackendUrl();
  const resp = await fetch(`${base}${pathWithQuery}`, {
    headers: { 'X-API-Key': apiKey || getDefaultApiKey() },
  });
  if (!resp.ok) throw new Error(await resp.text().catch(() => `HTTP ${resp.status}`));
  return resp.json();
}

/**
 * sendRequest – retrocompatível com a sua assinatura antiga.
 *
 * Exemplo novo:
 *   sendRequest('POST', '/devices/<id>/wifi', {
 *     body: { ssid, password },
 *     query: { connection_request: true },
 *     apiKey: '...'
 *   })
 *
 * Exemplo antigo (continua funcionando):
 *   sendRequest('POST', '/devices/<id>/wifi', {ssid, password}, {connection_request: true}, 'apiKey')
 */
export async function sendRequest(method, path, arg3, arg4, arg5) {
  let body, query, apiKey;
  const looksLikeOptionsObject =
    arg3 && typeof arg3 === 'object' && (
      Object.prototype.hasOwnProperty.call(arg3, 'body') ||
      Object.prototype.hasOwnProperty.call(arg3, 'query') ||
      Object.prototype.hasOwnProperty.call(arg3, 'apiKey')
    );

  if (looksLikeOptionsObject) {
    body = arg3.body;
    query = arg3.query || {};
    apiKey = arg3.apiKey;
  } else {
    body = arg3;
    query = arg4 || {};
    apiKey = arg5;
  }

  const baseUrl = getBackendUrl();
  const qs = toQueryString(query);
  const url = `${baseUrl}${path}${qs ? `?${qs}` : ''}`;

  const headers = { 'Content-Type': 'application/json' };
  const key = apiKey || getDefaultApiKey();
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
  const ct = resp.headers.get('content-type') || '';
  return ct.includes('application/json') ? resp.json() : null;
}

/* ===== Métricas ===== */

export async function getMetricsOverview(apiKey, params = {}) {
  const qs = toQueryString(params);
  return getJSON(`/metrics/overview${qs ? `?${qs}` : ''}`, apiKey);
}

export function openMetricsStream(apiKey, params = {}) {
  const base = getBackendUrl();
  const qs = toQueryString({
    token: apiKey || getDefaultApiKey(),
    interval: params.interval ?? 5,
    window_online_sec: params.window_online_sec ?? 600,
    window_24h_sec: params.window_24h_sec ?? 86400,
  });
  return new EventSource(`${base}/metrics/stream?${qs}`);
}

/* ===== Lista de devices ===== */

export async function listDevices(apiKey, params = {}) {
  const qs = toQueryString(params);
  return getJSON(`/devices/list${qs ? `?${qs}` : ''}`, apiKey);
}
