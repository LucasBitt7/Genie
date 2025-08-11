import React from 'react';
import ReactDOM from 'react-dom';
import App from './App';

// Ponto de entrada da aplicação. Renderiza o componente App dentro da div root.
ReactDOM.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
  document.getElementById('root')
);