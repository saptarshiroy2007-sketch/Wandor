import { useEffect, useState } from 'react';
import { listDueFees } from '../api/client';

interface FeeRecord {
  id: string;
  student_id: string;
  amount_due: number;
  amount_paid: number;
  is_paid: boolean;
  due_date: string;
}

function statusPill(fee: FeeRecord) {
  if (fee.is_paid) return 'bg-teal-50 text-teal-700';
  return 'bg-amber-50 text-amber-700';
}

function statusLabel(fee: FeeRecord) {
  if (fee.is_paid) return 'Paid';
  return 'Due';
}

export default function Payments() {
  const [fees, setFees] = useState<FeeRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listDueFees()
      .then(setFees)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <h1 className="font-display text-2xl font-semibold text-ink tracking-tight mb-6">
        Fee tracker
      </h1>

      {/* Loading */}
      {loading && (
        <p className="text-sm text-ink/50 text-center py-12">Loading fees…</p>
      )}

      {/* Empty state */}
      {!loading && fees.length === 0 && (
        <div className="border-2 border-dashed border-black/10 rounded-xl px-6 py-12 text-center">
          <p className="text-sm text-ink/50">No fee records yet.</p>
        </div>
      )}

      {!loading && fees.length > 0 && (
        <>
          {/* ── Mobile: stacked cards ── */}
          <div className="md:hidden space-y-3">
            {fees.map((f) => (
              <div
                key={f.id}
                className="bg-white rounded-xl border border-black/5 px-4 py-3.5"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-ink">
                    {f.student_id}
                  </span>
                  <span
                    className={`text-xs font-medium px-2.5 py-1 rounded-full ${statusPill(f)}`}
                  >
                    {statusLabel(f)}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-ink/60">
                  <span>Due: ₹{f.amount_due}</span>
                  <span>Paid: ₹{f.amount_paid}</span>
                  <span>Due by {new Date(f.due_date).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
          </div>

          {/* ── Desktop: proper table ── */}
          <div className="hidden md:block bg-white rounded-xl border border-black/5 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-black/5 text-ink/50 text-xs font-medium uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Student</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Due</th>
                  <th className="text-left px-4 py-3">Paid</th>
                  <th className="text-left px-4 py-3">Due date</th>
                </tr>
              </thead>
              <tbody>
                {fees.map((f) => (
                  <tr key={f.id} className="border-b border-black/5 last:border-0">
                    <td className="px-4 py-3 font-medium text-ink">
                      {f.student_id}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`text-xs font-medium px-2.5 py-1 rounded-full ${statusPill(f)}`}
                      >
                        {statusLabel(f)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink/70">₹{f.amount_due}</td>
                    <td className="px-4 py-3 text-ink/70">₹{f.amount_paid}</td>
                    <td className="px-4 py-3 text-ink/70">
                      {new Date(f.due_date).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

