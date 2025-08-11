import React, { useContext } from 'react';
import { Link } from 'react-router-dom';
import { ApiKeyContext } from '../App';

/**
 * Barra de navegação superior. Exibe links para todas as páginas e o estado da API Key.
 */
function NavBar() {
  const { apiKey } = useContext(ApiKeyContext);
  const keyStatus = apiKey ? 'API Key definida' : 'API Key não definida';
  return (
    <div style={{ backgroundColor: '#007ACC', color: 'white', padding: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ display: 'flex', gap: '1rem' }}>
        <Link to="/" style={{ color: 'white', textDecoration: 'none' }}>Home</Link>
        <Link to="/config" style={{ color: 'white', textDecoration: 'none' }}>Config</Link>
        <Link to="/cadastrar" style={{ color: 'white', textDecoration: 'none' }}>Cadastrar</Link>
        <Link to="/wifi" style={{ color: 'white', textDecoration: 'none' }}>Wi‑Fi</Link>
        <Link to="/pppoe" style={{ color: 'white', textDecoration: 'none' }}>PPPoE</Link>
        <Link to="/reboot" style={{ color: 'white', textDecoration: 'none' }}>Reboot</Link>
        <Link to="/factory-reset" style={{ color: 'white', textDecoration: 'none' }}>Reset</Link>
        <Link to="/params" style={{ color: 'white', textDecoration: 'none' }}>Parâmetros</Link>
      </div>
      <div>{keyStatus}</div>
    </div>
  );
}

export default NavBar;