import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function RoleSelect() {
  const [showStudentOptions, setShowStudentOptions] = useState(false);
  const navigate = useNavigate();

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}>
        <span className="brand-mark">W</span>
        <span className="brand-word" style={{ fontSize: 26 }}>Wandor</span>
      </div>
      <p>Who's logging in?</p>

      <div className="stack">
        <button onClick={() => navigate('/login')}>Teacher</button>

        <button
          className="btn"
          style={{ background: 'var(--surface)', color: 'var(--ink)' }}
          onClick={() => navigate('/institute-login')}
        >
          Institute owner
        </button>

        {!showStudentOptions ? (
          <button
            className="btn"
            style={{ background: 'var(--surface)', color: 'var(--ink)' }}
            onClick={() => setShowStudentOptions(true)}
          >
            Student
          </button>
        ) : (
          <div className="card stack">
            <p style={{ margin: 0 }}>Student</p>
            <button onClick={() => navigate('/student-login')}>Student login</button>
            <button
              className="btn"
              style={{ background: 'var(--surface)', color: 'var(--ink)' }}
              onClick={() => navigate('/parent-login')}
            >
              Parent login
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
