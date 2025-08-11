import React, { useContext } from 'react';
import { ApiKeyContext } from '../App';
import { Link } from 'react-router-dom';

/**
 * Página inicial. Exibe mensagem e alerta se a API Key ainda não foi configurada.
 */
function Home() {
  const { apiKey } = useContext(ApiKeyContext);
  return (
    <div style={{ maxWidth: '600px', margin: '1rem auto', padding: '1.5rem', background: 'white', borderRadius: '4px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)' }}>
      <h2>Bem-vindo ao Painel GenieACS</h2>
      <p>Use o menu para acessar as operações disponíveis.</p>
      {!apiKey && (
        <p style={{ color: 'red' }}>API Key não definida. Vá até <Link to="/config">Config</Link> para defini-la.</p>
      )}
    </div>
  );
}

export default Home;