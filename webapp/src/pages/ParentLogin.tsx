import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { parentLogin } from '../api/client';

export default function ParentLogin() {
  const [studentPhone, setStudentPhone] = useState('');
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      await parentLogin(studentPhone, pin);
      navigate('/parent');
    } catch {
      // Same 401 whether the PIN's wrong or the parent view was never activated
      // for this child (parent_pin_hash is null until a teacher sets one) -
      // no reason to leak which case it is.
      setError('Wrong phone number or PIN. If this is your first time, ask the teacher to set up your parent PIN.');
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, paddingTop: '15vh' }}>
      <h1>Wandor</h1>
      <p>Log in with your child's phone number and the PIN their teacher gave you.</p>
      <form onSubmit={handleSubmit} className="card stack">
        <input placeholder="Child's phone" value={studentPhone} onChange={(e) => setStudentPhone(e.target.value)} />
        <input placeholder="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">Log in</button>
      </form>
      <p className="hstack" style={{ justifyContent: 'center', marginTop: 16 }}>
        <Link to="/login">Teacher login</Link> · <Link to="/student-login">Student login</Link>
      </p>
    </div>
  );
}
