// src/pages/Dashboard.jsx
//
// Página única: cards (SSE) + tabela de devices (filtros/paginação)
// Usa ApiKeyContext do seu App.

import React, { useContext, useEffect, useMemo, useRef, useState } from 'react';
import { ApiKeyContext } from '../App';
import { getBackendUrl, openMetricsStream, listDevices } from '../utils/api';

export default function Dashboard() {
  const { apiKey } = useContext(ApiKeyContext);

  /* ========= Cards via SSE ========= */
  const [overview, setOverview] = useState(null);
  const [sseError, setSseError] = useState('');
  const esRef = useRef(null);

  useEffect(() => {
    if (!apiKey) { setSseError('Defina sua API Key em Config.'); return; }
    const es = openMetricsStream(apiKey, { interval: 5, window_online_sec: 600 });
    esRef.current = es;
    const onOverview = (evt) => {
      try { setOverview(JSON.parse(evt.data)); setSseError(''); }
      catch { setSseError('Falha ao parsear evento SSE'); }
    };
    es.addEventListener('overview', onOverview);
    es.onerror = () => setSseError('Conexão SSE caiu (recarregue a página)');
    return () => { es.removeEventListener('overview', onOverview); es.close(); };
  }, [apiKey]);

  /* ========= Lista de devices ========= */
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [tag, setTag] = useState('');
  const [productClass, setProductClass] = useState('');
  const [onlyOnline, setOnlyOnline] = useState(false);
  const [onlineWithin, setOnlineWithin] = useState(600);
  const [sortBy, setSortBy] = useState('_lastInform');
  const [order, setOrder] = useState('desc');
  const [listError, setListError] = useState('');
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(true);

  const params = useMemo(() => ({
    page,
    page_size: pageSize,
    search: search || undefined,
    tag: tag || undefined,
    product_class: productClass || undefined,
    only_online: onlyOnline,
    online_within_sec: onlineWithin,
    sort_by: sortBy,
    order,
  }), [page, pageSize, search, tag, productClass, onlyOnline, onlineWithin, sortBy, order]);

  // Helper para render seguro (nunca mostrar [object Object])
  const show = (v) =>
    (v === null || v === undefined || v === '') ? '-' :
    (typeof v === 'object') ? '-' : v;

  useEffect(() => {
    if (!apiKey) { setListError('Defina sua API Key em Config.'); return; }
    let stop = false;
    async function load() {
      try {
        setLoading(true);
        const data = await listDevices(apiKey, params);
        if (!stop) {
          setRows(data.items || []);
          setTotal(data.total || 0);
          setListError('');
        }
      } catch (e) {
        if (!stop) setListError(String(e.message || e));
      } finally {
        if (!stop) setLoading(false);
      }
    }
    load();
    if (!auto) return () => { stop = true; };
    const id = setInterval(load, 5000);
    return () => { stop = true; clearInterval(id); };
  }, [apiKey, params, auto]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div style={{ maxWidth: 1150, margin: '1rem auto', padding: '1rem' }}>
      <h2>Dashboard (ao vivo via SSE)</h2>

      {sseError && <Banner type="error">{sseError}</Banner>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, margin: '12px 0' }}>
        <Card title="Total" value={overview?.total_devices ?? '…'} />
        <Card title="Online (10min)" value={overview?.online_now ?? '…'} />
        <Card title="Ativos (24h)" value={overview?.active_24h ?? '…'} />
        <Card title="Offline (24h)" value={overview?.offline_24h ?? '…'} />
      </div>

      <h3 style={{ marginTop: 24 }}>Devices</h3>
      {listError && <Banner type="error">{listError}</Banner>}
      {/* Filtros */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', gap: 8, margin: '8px 0' }}>
        <input placeholder="Buscar por ID (regex)" value={search}
               onChange={e => { setPage(1); setSearch(e.target.value); }} />
        <input placeholder="Tag" value={tag}
               onChange={e => { setPage(1); setTag(e.target.value); }} />
        <input placeholder="ProductClass" value={productClass}
               onChange={e => { setPage(1); setProductClass(e.target.value); }} />
        <select value={onlineWithin} onChange={e => setOnlineWithin(Number(e.target.value))}>
          <option value={300}>Online (5 min)</option>
          <option value={600}>Online (10 min)</option>
          <option value={900}>Online (15 min)</option>
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={onlyOnline}
                 onChange={e => { setPage(1); setOnlyOnline(e.target.checked); }} />
          Somente online
        </label>
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>◀</button>
        <span>Página {page} / {totalPages}</span>
        <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>▶</button>
        <select value={pageSize} onChange={e => { setPage(1); setPageSize(Number(e.target.value)); }}>
          {[10,25,50,100].map(s => <option key={s} value={s}>{s} / pág</option>)}
        </select>
        <select value={sortBy} onChange={e => setSortBy(e.target.value)}>
          <option value="_lastInform">Ordenar por Last Inform</option>
          <option value="_id">Ordenar por ID</option>
        </select>
        <select value={order} onChange={e => setOrder(e.target.value)}>
          <option value="desc">Desc</option>
          <option value="asc">Asc</option>
        </select>
        <label style={{ marginLeft: 'auto' }}>
          <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> Auto refresh (5s)
        </label>
        <button onClick={() => setPage(p => p)} disabled={loading}>Atualizar</button>
      </div>

      {/* Tabela */}
      <table style={{ width: '100%', borderCollapse: 'collapse', background: 'white', border: '1px solid #eee', borderRadius: 8 }}>
        <thead>
          <tr style={{ background: '#f7f9fc' }}>
            <Th>ID</Th>
            <Th>Online</Th>
            <Th>Last Inform (UTC)</Th>
            <Th>Product</Th>
            <Th>SW</Th>
            <Th>SSID</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderTop: '1px solid #eee' }}>
              <Td mono>{show(r.device_id)}</Td>
              <Td>{r.online ? '🟢' : '⚪'}</Td>
              <Td mono>{show(r.last_inform)}</Td>
              <Td>{show(r.product_class)}</Td>
              <Td>{show(r.software_version)}</Td>
              <Td>{show(r.ssid)}</Td>
            </tr>
          ))}
          {!rows.length && (
            <tr><td colSpan={6} style={{ padding: 16, textAlign: 'center', color: '#777' }}>
              {loading ? 'Carregando…' : 'Sem resultados'}
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ---- UI helpers ---- */
function Card({ title, value }) {
  return (
    <div style={{ background: 'white', border: '1px solid #eee', borderRadius: 8, padding: 16, textAlign: 'center', boxShadow: '0 1px 2px rgba(0,0,0,.04)' }}>
      <div style={{ fontSize: 12, color: '#666' }}>{title}</div>
      <div style={{ fontSize: 28, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
function Banner({ children, type = 'info' }) {
  const colors = type === 'error'
    ? { bg: '#fdecea', border: '#f5c2c7' }
    : { bg: '#eef6ff', border: '#b6daff' };
  return (
    <div style={{ padding: '0.75rem', background: colors.bg, border: `1px solid ${colors.border}`, borderRadius: 6 }}>
      {children}
    </div>
  );
}
function Th({ children }) {
  return <th style={{ textAlign: 'left', padding: 8, fontSize: 12, color: '#666' }}>{children}</th>;
}
function Td({ children, mono }) {
  return <td style={{ padding: 8, fontFamily: mono ? 'ui-monospace, SFMono-Regular, Menlo, monospace' : undefined }}>{children}</td>;
}
