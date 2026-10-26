import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { parentLogin, AccountChoiceError } from '../api/client';

export default function ParentLogin() {
  const [studentPhone, setStudentPhone] = useState('');
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [choices, setChoices] = useState<{ student_id: string; label: string }[] | null>(null);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent, studentId?: string) {
    e.preventDefault();
    setError('');
    try {
      await parentLogin(studentPhone, pin, studentId);
      navigate('/parent');
    } catch (err: any) {
      if (err instanceof AccountChoiceError) { setChoices(err.choices); return; }
      if (err?.response?.status === 429) { setError('Too many attempts. Please wait a minute and try again.'); return; }
      // Same 401 whether the PIN's wrong or the parent view was never activated
      // for this child (parent_pin_hash is null until a teacher sets one) -
      // no reason to leak which case it is.
      setError('Wrong phone number or PIN. If this is your first time, ask the teacher to set up your parent PIN.');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}>
        <span className="brand-mark">W</span>
        <span className="brand-word" style={{ fontSize: 26 }}>Wandor</span>
      </div>
      <p>Log in with your child's phone number and the PIN their teacher gave you.</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Child's phone" value={studentPhone} onChange={(e) => setStudentPhone(e.target.value)} />
        <input placeholder="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Log in</button>
      </form>
      {choices && (
        <div className="card stack">
          <p style={{ margin: 0 }}>More than one child uses this number and PIN. Which one?</p>
          {choices.map((c) => (
            <button key={c.student_id} type="button" className="btn-ghost" onClick={(e) => handleSubmit(e, c.student_id)}>{c.label}</button>
          ))}
        </div>
      )}
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/login">Teacher login</Link> · <Link to="/student-login">Student login</Link>
      </p>
    </div>
  );
}
