import { NavLink, useNavigate } from 'react-router-dom';
import { logout, getRole } from '../api/client';

const TEACHER_LINKS = [
  { to: '/', label: 'Classes' },
  { to: '/students', label: 'Students' },
  { to: '/create-test', label: 'Tests' },
  { to: '/attendance', label: 'Attendance' },
  { to: '/payments', label: 'Fees' },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const role = getRole();

  function handleLogout() {
    logout();
    window.location.href = '/';
  }

  return (
    <div>
      <div className="nav">
        <div className="nav-inner">
          <span className="brand">Wandor</span>
          <div className="hstack">
            {role === 'teacher' && (
              <div className="nav-links">
                {TEACHER_LINKS.map((l) => (
                  <NavLink key={l.to} to={l.to} end className={({ isActive }) => (isActive ? 'active' : '')}>
                    {l.label}
                  </NavLink>
                ))}
              </div>
            )}
            <button className="btn-ghost btn-sm" onClick={handleLogout}>Log out</button>
          </div>
        </div>
      </div>
      <div className="page">{children}</div>
    </div>
  );
}
