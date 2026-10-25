import React from 'react';
import { createRoot } from 'react-dom/client';
import LocalDashboard from './LocalDashboard';

createRoot(document.getElementById('root')!).render(<React.StrictMode><LocalDashboard /></React.StrictMode>);
