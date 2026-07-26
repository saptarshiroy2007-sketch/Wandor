import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import ScheduleClass from './pages/ScheduleClass';
import TakeTest from './pages/TakeTest';
import Payments from './pages/Payments';
import AppShell from './components/AppShell';
import './index.css';

function isLoggedIn() {
  return !!localStorage.getItem('wandor_token');
}

function Protected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() ? <AppShell>{children}</AppShell> : <Navigate to="/login" />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Protected><Dashboard /></Protected>} />
        <Route path="/schedule" element={<Protected><ScheduleClass /></Protected>} />
        <Route path="/payments" element={<Protected><Payments /></Protected>} />
        <Route path="/test/:testId" element={<TakeTest />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);

