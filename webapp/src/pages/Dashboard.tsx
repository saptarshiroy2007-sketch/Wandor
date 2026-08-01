import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listClasses, cancelClass } from '../api/client';
import Layout from '../components/Layout';

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
    <Layout>
      <div className="row">
        <h1>Classes</h1>
        <Link to="/schedule" className="btn btn-sm">+ Schedule</Link>
      </div>

      {classes.length === 0 ? (
        <p className="empty">No classes scheduled yet.</p>
      ) : (
        classes
          .slice()
          .sort((a, b) => +new Date(b.start_time) - +new Date(a.start_time))
          .map((c) => (
            <div className="card row" key={c.id}>
              <div>
                <div>{c.subject} — {c.batch}</div>
                <p style={{ margin: '2px 0 0' }}>{new Date(c.start_time).toLocaleString()}</p>
              </div>
              <div className="hstack">
                <span className={`badge ${c.status === 'cancelled' ? 'badge-danger' : c.status === 'completed' ? 'badge-muted' : ''}`}>
                  {c.status}
                </span>
                {c.status === 'scheduled' && (
                  <button className="btn-ghost btn-sm" onClick={() => handleCancel(c.id)}>Cancel</button>
                )}
              </div>
            </div>
          ))
      )}
    </Layout>
  );
}
