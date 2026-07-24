import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listClasses, cancelClass } from '../api/client';

interface ClassSession {
  id: string;
  batch: string;
  subject: string;
  start_time: string;
  status: string;
}

export default function Dashboard() {
  const [classes, setClasses] = useState<ClassSession[]>([]);

  useEffect(() => {
    listClasses().then(setClasses);
  }, []);

  async function handleCancel(id: string) {
    const reason = prompt('Reason for cancelling? (optional)') || undefined;
    await cancelClass(id, reason);
    setClasses(await listClasses());
  }

  return (
    <div>
      <h1>Wandor</h1>
      <Link to="/schedule">+ Schedule a class</Link>
      <Link to="/payments">Fee tracker</Link>

      <ul>
        {classes.map((c) => (
          <li key={c.id}>
            {c.subject} — {c.batch} — {new Date(c.start_time).toLocaleString()} — {c.status}
            {c.status === 'scheduled' && (
              <button onClick={() => handleCancel(c.id)}>Cancel</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
