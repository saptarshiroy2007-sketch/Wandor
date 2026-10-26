import { useState } from 'react';
import { isDarkTheme, setTheme } from '../api/client';

// Same switch Settings uses (data-theme on <html> + wandor_theme in localStorage),
// for screens that have no nav or Settings link, such as the platform admin.
export default function ThemeToggle() {
  const [dark, setDark] = useState(isDarkTheme());
  return (
    <button
      type="button"
      className="btn-ghost btn-sm"
      aria-pressed={dark}
      onClick={() => { setTheme(!dark); setDark(!dark); }}
    >
      {dark ? 'Light mode' : 'Dark mode'}
    </button>
  );
}
