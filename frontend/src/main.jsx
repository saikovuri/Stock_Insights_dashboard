import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppRoot } from './App';
import { initMonitoring } from './monitoring';
import ErrorBoundary from './components/ErrorBoundary';
import './App.css';

initMonitoring();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary><AppRoot /></ErrorBoundary>
  </React.StrictMode>
);
