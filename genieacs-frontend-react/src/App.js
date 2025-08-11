// src/App.js (trecho essencial)
import React, { createContext, useEffect, useState } from 'react';
import { HashRouter as Router, Switch, Route, Redirect } from 'react-router-dom';
import NavBar from './components/NavBar';
import Home from './pages/Home';
import Config from './pages/Config';
import Cadastrar from './pages/Cadastrar';
import Wifi from './pages/Wifi';
import Pppoe from './pages/Pppoe';
import Reboot from './pages/Reboot';
import FactoryReset from './pages/FactoryReset';
import Params from './pages/Params';

export const ApiKeyContext = createContext();

export default function App() {
  const [apiKey, setApiKey] = useState('');

  useEffect(() => {
    setApiKey(localStorage.getItem('genieacs_api_key') || '');
  }, []);

  useEffect(() => {
    if (apiKey) localStorage.setItem('genieacs_api_key', apiKey);
  }, [apiKey]);

  return (
    <Router>
      <ApiKeyContext.Provider value={{ apiKey, setApiKey }}>
        <NavBar />
        <Switch>
          <Route path="/config" component={Config} />
          <Route path="/cadastrar" component={Cadastrar} />
          <Route path="/wifi" component={Wifi} />
          <Route path="/pppoe" component={Pppoe} />
          <Route path="/reboot" component={Reboot} />
          <Route path="/factory-reset" component={FactoryReset} />
          <Route path="/params" component={Params} />
          <Route exact path="/" component={Home} />
          <Redirect to="/" />
        </Switch>
      </ApiKeyContext.Provider>
    </Router>
  );
}
