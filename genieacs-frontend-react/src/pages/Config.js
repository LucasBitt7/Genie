// src/pages/Config.js
import React, { useContext, useState, useEffect } from 'react';
import { ApiKeyContext } from '../App';

function Config() {
  const { apiKey, setApiKey } = useContext(ApiKeyContext);
  const [value, setValue] = useState('');
  const [backendUrl, setBackendUrl] = useState('');

  useEffect(() => {
    setValue(apiKey || '');
    setBackendUrl(localStorage.getItem('genieacs_backend_url') || 'http://localhost:8000');
  }, [apiKey]);

  function save() {
    setApiKey(value.trim());
    localStorage.setItem('genieacs_backend_url', backendUrl.trim());
    alert('Configurações salvas.');
  }

  return (
    <div style={{ maxWidth: 600, margin: '1rem auto', background: '#fff', padding: '1rem', borderRadius: 8 }}>
      <h2>Configuração</h2>

      <label>API Key (X-API-Key)</label>
      <input
        type="text"
        placeholder="cole sua API Key"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{ width: '100%', padding: '0.6rem', marginBottom: '1rem' }}
      />

      <label>Backend URL</label>
      <input
        type="text"
        placeholder="http://localhost:8000"
        value={backendUrl}
        onChange={(e) => setBackendUrl(e.target.value)}
        style={{ width: '100%', padding: '0.6rem', marginBottom: '1rem' }}
      />

      <button onClick={save}>Salvar</button>
      <p style={{ marginTop: '0.8rem', color: '#555' }}>
        O frontend conversa apenas com o <strong>backend FastAPI</strong>. O backend, por sua vez,
        fala com o GenieACS via <code>GENIEACS_NBI_URL</code>.
      </p>
    </div>
  );
}

export default Config;
