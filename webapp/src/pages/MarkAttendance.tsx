import { useEffect, useState } from 'react';
import { listClasses, listStudents, markAttendance, getClassAttendance } from '../api/client';
import Layout from '../components/Layout';

interface ClassSession { id: string; batch: string; subject: string; start_time: string; status: string; }
interface StudentOut { id: string; name: string; phone: string; batch?: string | null; }

export default function MarkAttendance() {
  const [classes, setClasses] = useState<ClassSession[]>([]);
  const [classId, setClassId] = useState('');
  const [students, setStudents] = useState<StudentOut[]>([]);
  const [present, setPresent] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { listClasses().then(setClasses); }, []);

  const selected = classes.find((c) => c.id === classId);

  useEffect(() => {
    if (!selected) { setStudents([]); return; }
    setSaved(false);
    listStudents(selected.batch).then(async (roster) => {
      setStudents(roster);
      const existing = await getClassAttendance(classId).catch(() => []);
      const marks: Record<string, boolean> = {};
      roster.forEach((s: StudentOut) => { marks[s.id] = true; });
      existing.forEach((r: any) => { marks[r.student_id] = r.present; });
      setPresent(marks);
    });
  }, [classId]);

  async function handleSave() {
    setSaving(true);
    try {
      await markAttendance(classId, students.map((s) => ({ student_id: s.id, present: !!present[s.id] })));
      setSaved(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Layout>
      <h1>Attendance</h1>

      <div className="card">
        <label>Class session</label>
        <select value={classId} onChange={(e) => setClassId(e.target.value)}>
          <option value="">Select a class…</option>
          {classes
            .slice()
            .sort((a, b) => +new Date(b.start_time) - +new Date(a.start_time))
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.subject} — {c.batch} — {new Date(c.start_time).toLocaleDateString()}
              </option>
            ))}
        </select>
      </div>

      {selected && (
        <>
          <h2>{selected.batch} ({students.length})</h2>
          {students.length === 0 ? (
            <p className="empty">No students in this batch.</p>
          ) : (
            <div className="stack">
              {students.map((s) => (
                <label key={s.id} className="card row" style={{ cursor: 'pointer', margin: 0 }}>
                  <span>{s.name}</span>
                  <span className="omr-option" style={{ padding: 0 }}>
                    <input
                      type="checkbox"
                      checked={!!present[s.id]}
                      onChange={(e) => setPresent((prev) => ({ ...prev, [s.id]: e.target.checked }))}
                    />
                    <span className="omr-bubble square" />
                  </span>
                </label>
              ))}
            </div>
          )}
          {students.length > 0 && (
            <div className="hstack" style={{ marginTop: 12 }}>
              <button onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save attendance'}</button>
              {saved && <span style={{ color: 'var(--accent)', fontSize: 13 }}>Saved.</span>}
            </div>
          )}
        </>
      )}
    </Layout>
  );
}
