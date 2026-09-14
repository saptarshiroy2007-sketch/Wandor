import { NavLink, useNavigate } from 'react-router-dom';
import { logout, getRole } from '../api/client';

// ── Teacher: 5 destinations ──────────────────────────────────────────────────
const TEACHER_LINKS = [
  { to: '/',             label: 'Classes',    end: true  },
  { to: '/students',     label: 'Students',   end: false },
  { to: '/create-test',  label: 'Tests',      end: false },
  { to: '/attendance',   label: 'Attendance', end: false },
  { to: '/payments',     label: 'Fees',       end: false },
];

// ── Institute admin: 4-tab shell. Students + Analytics disabled until routes ship.
// Both Institute and Teachers currently resolve to /institute (one page, two sections).
// The nav shape is stable; individual tabs will gain their own routes as features land.
const INSTITUTE_LINKS = [
  { to: '/institute', label: 'Institute', end: true,  disabled: false },
  { to: '/institute', label: 'Teachers',  end: false, disabled: false },
  { to: null,         label: 'Students',             disabled: true  },
  { to: null,         label: 'Analytics',            disabled: true  },
];

type NavItem =
  | { to: string; label: string; end: boolean; disabled: false }
  | { to: null;   label: string;               disabled: true  };

function getLinks(role: string | null): NavItem[] {
  if (role === 'teacher')       return TEACHER_LINKS as NavItem[];
  if (role === 'institute_admin') return INSTITUTE_LINKS as NavItem[];
  return [];
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const role = getRole();
  const links = getLinks(role);

  function handleLogout() {
    logout();
    window.location.href = '/';
  }

  return (
    <div>
      {/* ── Top bar ──────────────────────────────────────────── */}
      <nav className="nav">
        <div className="nav-inner">
          {/* Brand */}
          <span className="brand">
            <span className="brand-mark">W</span>
            <span className="brand-word">Wandor</span>
          </span>

          {/* Desktop nav links — hidden on phone via CSS */}
          {links.length > 0 && (
            <div className="nav-links">
              {links.map((l) =>
                l.disabled ? (
                  <span key={l.label} className="nav-tab-disabled" title="Coming soon">
                    {l.label}
                  </span>
                ) : (
                  <NavLink
                    key={l.label}
                    to={l.to}
                    end={l.end}
                    className={({ isActive }) => (isActive ? 'active' : '')}
                  >
                    {l.label}
                  </NavLink>
                )
              )}
            </div>
          )}

          <NavLink to="/settings" className="nav-logout" title="Settings" style={{ textDecoration: 'none' }}>
            ⚙
          </NavLink>
          <button className="nav-logout" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </nav>

      {/* ── Page content ─────────────────────────────────────── */}
      <div className="page">{children}</div>

      {/* ── Bottom tab bar (phone only, via CSS display:none on desktop) ── */}
      {links.length > 0 && (
        <div className="bottom-tab-bar">
          <div className="bottom-tab-bar-inner">
            {links.map((l) =>
              l.disabled ? (
                <span key={l.label} className="bottom-tab disabled" title="Coming soon">
                  {l.label}
                </span>
              ) : (
                <NavLink
                  key={l.label}
                  to={l.to}
                  end={l.end}
                  className={({ isActive }) =>
                    isActive ? 'bottom-tab active' : 'bottom-tab'
                  }
                >
                  {l.label}
                </NavLink>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
