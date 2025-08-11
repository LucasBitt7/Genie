import React, { useContext, useState } from 'react';
import { ApiKeyContext } from '../App';
import { sendRequest } from '../utils/api';

/**
 * Página para alterar apenas o Wi‑Fi.
 */
function Wifi() {
  const { apiKey } = useContext(ApiKeyContext);
  const [deviceId, setDeviceId] = useState('');
  const [ssid, setSsid] = useState('');
  const [wifiPass, setWifiPass] = useState('');
  const [connReq, setConnReq] = useState(true);
  const [response, setResponse] = useState('');
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!apiKey) {
      setResponse('Defina sua API Key em Config.');
      return;
    }
    setResponse('Enviando...');
    try {
      const result = await sendRequest('POST', `/devices/${encodeURIComponent(deviceId)}/wifi`, {
        ssid: ssid,
        password: wifiPass
      }, { connection_request: connReq }, apiKey);
      setResponse('Task enviada. ID: ' + result._id);
    } catch (err) {
      setResponse('Erro: ' + err.message);
    }
  };
  return (
    <div style={{ maxWidth: '600px', margin: '1rem auto', padding: '1.5rem', background: 'white', borderRadius: '4px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
      <h2>Alterar Wi‑Fi</h2>
      <form onSubmit={handleSubmit}>
        <label>ID do dispositivo</label>
        <input type="text" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} required style={inputStyle} />
        <label>SSID</label>
        <input type="text" value={ssid} onChange={(e) => setSsid(e.target.value)} required style={inputStyle} />
        <label>Senha</label>
        <input type="password" value={wifiPass} onChange={(e) => setWifiPass(e.target.value)} required style={inputStyle} />
        <label>
          <input type="checkbox" checked={connReq} onChange={(e) => setConnReq(e.target.checked)} /> Connection Request imediato
        </label>
        <button type="submit" style={buttonStyle}>Enviar</button>
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

export default Wifi;