import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import './index.css';
import RoleSelect from './pages/RoleSelect';
import Login from './pages/Login';
import StudentLogin from './pages/StudentLogin';
import ParentLogin from './pages/ParentLogin';
import ParentDashboard from './pages/ParentDashboard';
import InstituteLogin from './pages/InstituteLogin';
import InstituteDashboard from './pages/InstituteDashboard';
import Dashboard from './pages/Dashboard';
import ScheduleClass from './pages/ScheduleClass';
import TakeTest from './pages/TakeTest';
import Payments from './pages/Payments';
import ManageStudents from './pages/ManageStudents';
import CreateTest from './pages/CreateTest';
import MarkAttendance from './pages/MarkAttendance';
import StudentHome from './pages/StudentHome';
import { getRole } from './api/client';

function isLoggedIn() {
  return !!localStorage.getItem('wandor_token');
}

function Protected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() ? <>{children}</> : <Navigate to="/login" />;
}

// Test-taking is student-only - a teacher token being present doesn't grant access here,
// since get_current_student on the backend would reject it anyway. Redirect to the
// student login screen specifically, not the teacher one.
function StudentProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'student' ? <>{children}</> : <Navigate to="/student-login" />;
}

// Same isolation as StudentProtected - a teacher or student token being present
// doesn't grant access to the parent dashboard, since get_current_parent on the
// backend would reject it anyway.
function ParentProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'parent' ? <>{children}</> : <Navigate to="/parent-login" />;
}

function InstituteProtected({ children }: { children: React.ReactNode }) {
  return isLoggedIn() && getRole() === 'institute_admin' ? <>{children}</> : <Navigate to="/institute-login" />;
}

// "/" used to always render the teacher Dashboard (which redirected logged-out
// visitors to /login), so opening the site landed straight on teacher login no
// matter who you were. Now it shows a role picker to logged-out visitors, and
// sends already-logged-in users straight to whichever dashboard matches their role.
function HomeRoute() {
  if (!isLoggedIn()) return <RoleSelect />;
  const role = getRole();
  if (role === 'student') return <Navigate to="/home" />;
  if (role === 'parent') return <Navigate to="/parent" />;
  if (role === 'institute_admin') return <Navigate to="/institute" />;
  return <Dashboard />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/student-login" element={<StudentLogin />} />
        <Route path="/parent-login" element={<ParentLogin />} />
        <Route path="/parent" element={<ParentProtected><ParentDashboard /></ParentProtected>} />
        <Route path="/institute-login" element={<InstituteLogin />} />
        <Route path="/institute" element={<InstituteProtected><InstituteDashboard /></InstituteProtected>} />
        <Route path="/home" element={<StudentProtected><StudentHome /></StudentProtected>} />
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
