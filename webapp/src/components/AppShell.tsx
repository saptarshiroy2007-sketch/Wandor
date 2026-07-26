import { ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { LayoutDashboard, CalendarPlus, Wallet, LogOut } from 'lucide-react';

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/schedule', label: 'Schedule', icon: CalendarPlus },
  { to: '/payments', label: 'Fees', icon: Wallet },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();

  function handleLogout() {
    localStorage.removeItem('wandor_token');
    navigate('/login');
  }

  return (
    <div className="min-h-screen bg-cream">
      {/* ── Desktop sidebar ── */}
      <aside className="hidden md:flex md:flex-col fixed inset-y-0 left-0 w-60 bg-white border-r border-black/5">
        {/* Wordmark */}
        <div className="px-5 pt-6 pb-4">
          <h1 className="font-display text-2xl font-semibold text-ink tracking-tight">
            Wandor
          </h1>
          <p className="text-xs text-ink/40 mt-0.5">Teacher dashboard</p>
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 space-y-1">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-teal-50 text-teal-800'
                    : 'text-ink/70 hover:text-ink hover:bg-black/5'
                }`
              }
            >
              <Icon size={18} strokeWidth={2} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Logout */}
        <div className="px-3 pb-5 mt-auto">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-ink/50 hover:text-red-600 hover:bg-red-50 w-full transition-colors"
          >
            <LogOut size={18} strokeWidth={2} />
            Log out
          </button>
        </div>
      </aside>

      {/* ── Mobile top bar ── */}
      <header className="md:hidden sticky top-0 z-30 bg-white border-b border-black/5 px-4 py-3 flex items-center justify-between">
        <h1 className="font-display text-lg font-semibold text-ink">Wandor</h1>
        <button
          onClick={handleLogout}
          className="text-ink/50 hover:text-red-600 transition-colors"
          aria-label="Log out"
        >
          <LogOut size={20} strokeWidth={2} />
        </button>
      </header>

      {/* ── Main content ── */}
      <main className="md:ml-60 md:min-h-screen pb-24 md:pb-0">
        <div className="max-w-3xl mx-auto px-4 py-6 md:py-8">{children}</div>
      </main>

      {/* ── Mobile bottom tab bar ── */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-30 bg-white border-t border-black/5 px-2 pb-safe-area">
        <div className="flex items-center justify-around py-1">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  isActive
                    ? 'text-teal-800'
                    : 'text-ink/50 hover:text-ink/70'
                }`
              }
            >
              <Icon size={20} strokeWidth={2} />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

