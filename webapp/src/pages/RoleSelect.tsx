import { Link } from 'react-router-dom';
import '../landing.css';

const DOORS = [
  { to: '/login', name: 'Teacher', note: 'Classes, attendance, tests, fees' },
  { to: '/institute-login', name: 'Institute', note: 'Your centre and its teachers' },
  { to: '/student-login', name: 'Student', note: 'Timetable, tests, results' },
  { to: '/parent-login', name: 'Parent', note: 'Attendance, results, fees' },
];

export default function RoleSelect() {
  return (
    <div className="lp lp-enter">
      <div className="lp-enter-left">
        <Link to="/" className="lp-logo" aria-label="Wandor home">
          <span className="lp-logo-mark" aria-hidden="true">W</span>
          <span className="lp-logo-word" style={{ color: 'var(--lp-ivory)' }}>Wandor</span>
        </Link>
        <h1 className="lp-enter-h">
          Who's<br />logging<br />in?
        </h1>
        <div className="lp-enter-circle" aria-hidden="true" />
      </div>

      <main className="lp-enter-right">
        <ul className="lp-doors">
          {DOORS.map((d, i) => (
            <li key={d.to}>
              <Link to={d.to} className="lp-door" style={{ ['--d' as string]: i }}>
                <span className="lp-door-name">{d.name}</span>
                <span className="lp-door-note">{d.note}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="lp-enter-new lp-label">
          New here? <Link to="/teacher-signup">Teacher sign up</Link> · <Link to="/institute-signup">Register an institute</Link>
        </p>
      </main>
    </div>
  );
}
