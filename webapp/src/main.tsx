import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import '@fontsource-variable/archivo/wdth.css';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
import './index.css';
import RoleSelect from './pages/RoleSelect';
import Landing from './pages/Landing';
import Login from './pages/Login';
import TeacherSignup from './pages/TeacherSignup';
import InstituteSignup from './pages/InstituteSignup';
import StudentLogin from './pages/StudentLogin';
import ParentLogin from './pages/ParentLogin';
import ParentDashboard from './pages/ParentDashboard';
import InstituteLogin from './pages/InstituteLogin';
import ForgotPassword from './pages/ForgotPassword';
import InstituteDashboard from './pages/InstituteDashboard';
import InstituteStudents from './pages/InstituteStudents';
import Dashboard from './pages/Dashboard';
import ScheduleClass from './pages/ScheduleClass';
import TakeTest from './pages/TakeTest';
import Payments from './pages/Payments';
import ManageStudents from './pages/ManageStudents';
import CreateTest from './pages/CreateTest';
import MarkAttendance from './pages/MarkAttendance';
import StudentHome from './pages/StudentHome';
import Settings from './pages/Settings';
import MyProfile from './pages/MyProfile';
import Billing from './pages/Billing';
import Receipt from './pages/Receipt';
import InvoicePage from './pages/InvoicePage';
import AdminLogin from './pages/AdminLogin';
import AdminDashboard from './pages/AdminDashboard';
import AccountLocked from './pages/AccountLocked';
import { getRole } from './api/client';

function isLoggedIn() {
  return !!localStorage.getItem('wandor_token');
}

function Protected({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn() || getRole() !== 'teacher') return <Navigate to="/login" />;
  return <>{children}</>;
}

// Any logged-in role can reach /settings — each role sees appropriate content there.
function LoggedInOnly({ children }: { children: React.ReactNode }) {
  if (!isLoggedIn()) return <Navigate to="/" />;
  return <>{children}</>;
}

function StudentProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'student' ? <>{children}</> : <Navigate to="/student-login" />;
}

function ParentProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'parent' ? <>{children}</> : <Navigate to="/parent-login" />;
}

function InstituteProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'institute_admin' ? <>{children}</> : <Navigate to="/institute-login" />;
}

// Billing is shared by exactly two roles: an independent teacher pays for themselves, an
// institute admin pays for the institute. (A teacher who belongs to an institute can
// open it too - it shows their institute's plan read-only.)
function BillingProtected({ children }: { children: React.ReactNode }) {
  const role = getRole();
  return isLoggedIn() && (role === 'teacher' || role === 'institute_admin') ? <>{children}</> : <Navigate to="/" />;
}

function AdminProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'platform_admin' ? <>{children}</> : <Navigate to="/admin-login" />;
}

function HomeRoute() {
  if (!isLoggedIn()) return <Landing />;
  const role = getRole();
  if (role === 'student') return <Navigate to="/home" />;
  if (role === 'parent') return <Navigate to="/parent" />;
  if (role === 'institute_admin') return <Navigate to="/institute" />;
  if (role === 'platform_admin') return <Navigate to="/admin" />;
  return <Dashboard />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/enter" element={<RoleSelect />} />
        <Route path="/login" element={<Login />} />
        <Route path="/teacher-signup" element={<TeacherSignup />} />
        <Route path="/institute-signup" element={<InstituteSignup />} />
        <Route path="/student-login" element={<StudentLogin />} />
        <Route path="/parent-login" element={<ParentLogin />} />
        <Route path="/admin-login" element={<AdminLogin />} />
        <Route path="/admin" element={<AdminProtected><AdminDashboard /></AdminProtected>} />
        <Route path="/account-locked" element={<AccountLocked />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/parent" element={<ParentProtected><ParentDashboard /></ParentProtected>} />
        <Route path="/institute-login" element={<InstituteLogin />} />
        <Route path="/institute" element={<InstituteProtected><InstituteDashboard /></InstituteProtected>} />
        <Route path="/institute/students" element={<InstituteProtected><InstituteStudents /></InstituteProtected>} />
        <Route path="/home" element={<StudentProtected><StudentHome /></StudentProtected>} />
        <Route path="/settings" element={<LoggedInOnly><Settings /></LoggedInOnly>} />
        <Route path="/my-profile" element={<LoggedInOnly><MyProfile /></LoggedInOnly>} />
        <Route path="/receipt/:paymentId" element={<LoggedInOnly><Receipt /></LoggedInOnly>} />
        <Route path="/billing" element={<BillingProtected><Billing /></BillingProtected>} />
        <Route path="/billing/invoice/:invoiceId" element={<BillingProtected><InvoicePage /></BillingProtected>} />
        <Route path="/" element={<HomeRoute />} />
        <Route path="/schedule" element={<Protected><ScheduleClass /></Protected>} />
        <Route path="/students" element={<Protected><ManageStudents /></Protected>} />
        <Route path="/create-test" element={<Protected><CreateTest /></Protected>} />
        <Route path="/attendance" element={<Protected><MarkAttendance /></Protected>} />
        <Route path="/payments" element={<Protected><Payments /></Protected>} />
        <Route path="/test/:testId" element={<StudentProtected><TakeTest /></StudentProtected>} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);


