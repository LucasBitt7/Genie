import React, { useContext, useState } from 'react';
import { ApiKeyContext } from '../App';
import { sendRequest } from '../utils/api';

/**
 * Página para resetar o dispositivo aos padrões de fábrica.
 */
function FactoryReset() {
  const { apiKey } = useContext(ApiKeyContext);
  const [deviceId, setDeviceId] = useState('');
  const [connReq, setConnReq] = useState(true);
  const [response, setResponse] = useState('');
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!apiKey) {
      setResponse('Defina sua API Key em Config.');
      return;
    }
    setResponse('Enviando reset...');
    try {
      const result = await sendRequest('POST', `/devices/${encodeURIComponent(deviceId)}/factory_reset`, {}, { connection_request: connReq }, apiKey);
      setResponse('Task enviada. ID: ' + result._id);
    } catch (err) {
      setResponse('Erro: ' + err.message);
    }
  };
  return (
    <div style={{ maxWidth: '600px', margin: '1rem auto', padding: '1.5rem', background: 'white', borderRadius: '4px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
      <h2>Resetar para Fábrica</h2>
      <form onSubmit={handleSubmit}>
        <label>ID do dispositivo</label>
        <input type="text" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} required style={inputStyle} />
        <label>
          <input type="checkbox" checked={connReq} onChange={(e) => setConnReq(e.target.checked)} /> Connection Request imediato
        </label>
        <button type="submit" style={buttonStyle}>Resetar</button>
      </form>
      {response && <div style={responseStyle}>{response}</div>}
    </div>
  );
}

const inputStyle = {
  width: '100%',
  padding: '0.5rem',
  marginTop: '0.25rem',
  border: '1px solid #ccc',
  borderRadius: '4px',
  boxSizing: 'border-box'
};
const buttonStyle = {
  width: '100%',
  padding: '0.5rem',
  marginTop: '1rem',
  backgroundColor: '#007ACC',
  color: 'white',
  border: 'none',
  borderRadius: '4px',
  fontSize: '1rem',
  cursor: 'pointer'
};
const responseStyle = {
  marginTop: '1rem',
  padding: '1rem',
  backgroundColor: '#f0f8ff',
  border: '1px solid #007ACC',
  borderRadius: '4px',
  whiteSpace: 'pre-wrap'
};

export default FactoryReset;