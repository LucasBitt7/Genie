import React, { useContext, useState } from 'react';
import { ApiKeyContext } from '../App';
import { sendRequest } from '../utils/api';

/**
 * Página para solicitar leitura de parâmetros arbitrários via getParameterValues.
 */
function Params() {
  const { apiKey } = useContext(ApiKeyContext);
  const [deviceId, setDeviceId] = useState('');
  const [rawParams, setRawParams] = useState('');
  const [connReq, setConnReq] = useState(true);
  const [response, setResponse] = useState('');
  const parseParams = (text) => {
    return text.split(/[\n,]/).map(p => p.trim()).filter(Boolean);
  };
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!apiKey) {
      setResponse('Defina sua API Key em Config.');
      return;
    }
    setResponse('Solicitando parâmetros...');
    try {
      const paramList = parseParams(rawParams);
      const result = await sendRequest('POST', `/devices/${encodeURIComponent(deviceId)}/parameters`, {
        parameter_names: paramList
      }, { connection_request: connReq }, apiKey);
      setResponse('Task enviada. ID: ' + result._id);
    } catch (err) {
      setResponse('Erro: ' + err.message);
    }
  };
  return (
    <div style={{ maxWidth: '600px', margin: '1rem auto', padding: '1.5rem', background: 'white', borderRadius: '4px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
      <h2>Ler Parâmetros</h2>
      <form onSubmit={handleSubmit}>
        <label>ID do dispositivo</label>
        <input type="text" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} required style={inputStyle} />
        <label>Parâmetros (uma por linha ou separados por vírgula)</label>
        <textarea value={rawParams} onChange={(e) => setRawParams(e.target.value)} required style={{ width: '100%', height: '100px', padding: '0.5rem', marginTop: '0.25rem', border: '1px solid #ccc', borderRadius: '4px', boxSizing: 'border-box' }}></textarea>
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

export default Params;