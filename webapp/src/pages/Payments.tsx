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

export default function Payments() {
  const [fees, setFees] = useState<FeeRecord[]>([]);

  useEffect(() => {
    listDueFees().then(setFees);
  }, []);

  return (
    <div>
      <h1>Fee tracker</h1>
      <table>
        <thead>
          <tr><th>Student</th><th>Due</th><th>Paid</th><th>Due date</th></tr>
        </thead>
        <tbody>
          {fees.map((f) => (
            <tr key={f.id}>
              <td>{f.student_id}</td>
              <td>₹{f.amount_due}</td>
              <td>₹{f.amount_paid}</td>
              <td>{new Date(f.due_date).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
