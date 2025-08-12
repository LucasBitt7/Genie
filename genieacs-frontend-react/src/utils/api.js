// src/utils/api.js

export function getBackendUrl() {
  return localStorage.getItem('genieacs_backend_url') || 'http://localhost:8000';
}

/**
 * Envia requisição ao backend FastAPI.
 *
 * Uso recomendado:
 *   sendRequest('POST', '/devices/<id>/wifi', {
 *     body: { ssid, password },
 *     query: { connection_request: true },
 *     apiKey: '...'
 *   })
 *
 * Retrocompatível com a forma antiga:
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
  const qs = new URLSearchParams(
    Object.entries(query).flatMap(([k, v]) =>
      v === undefined || v === null ? [] : [[k, String(v)]]
    )
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
