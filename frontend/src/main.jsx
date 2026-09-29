import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppRoot } from './App';
import { initMonitoring } from './monitoring';
import './App.css';

initMonitoring();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppRoot />
  </React.StrictMode>
);
