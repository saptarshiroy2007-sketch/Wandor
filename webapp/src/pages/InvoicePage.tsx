import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getInvoice, getSeller, Invoice, Seller } from '../api/client';
import { inrPaise, fmtDate } from '../lib/money';

/** Printable tax invoice for one subscription charge. Outside the app Layout (like Receipt) so
 *  "Print / save as PDF" produces just the invoice. Only whoever manages billing can open it. */
export default function InvoicePage() {
  const { invoiceId } = useParams();
  const nav = useNavigate();
  const [inv, setInv] = useState<Invoice | null>(null);
  const [seller, setSeller] = useState<Seller | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!invoiceId) return;
    getInvoice(invoiceId).then(setInv).catch(() => setError('Invoice not found.'));
    getSeller().then(setSeller).catch(() => setSeller(null));
  }, [invoiceId]);

  const row = (label: string, value: React.ReactNode) => (
    <div className="row" style={{ padding: '6px 0' }}>
      <span style={{ color: 'var(--muted)' }}>{label}</span><span style={{ color: 'var(--ink)' }}>{value}</span>
    </div>
  );

  return (
    <div style={{ maxWidth: 560, margin: '32px auto', padding: '0 16px' }}>
      <div className="no-print" style={{ marginBottom: 12 }}>
        <button className="btn-ghost btn-sm" onClick={() => nav(-1)}>← Back</button>{' '}
        {inv && <button className="btn-sm" onClick={() => window.print()}>Print / save as PDF</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {!inv && !error && <p className="empty">Loading…</p>}
      {inv && (
        <div className="card">
          <h1 style={{ marginTop: 0 }}>Tax invoice</h1>
          <div style={{ marginBottom: 12 }}>
            {seller && seller.legal_name ? (
              <>
                <strong style={{ color: 'var(--ink)' }}>{seller.legal_name}</strong>
                {seller.gstin && <div>GSTIN: {seller.gstin}</div>}
                {seller.address && <div style={{ whiteSpace: 'pre-line' }}>{seller.address}</div>}
              </>
            ) : (
              <span style={{ color: 'var(--muted)' }}>Seller details are not set up yet.</span>
            )}
          </div>
          <hr />
          {row('Invoice no.', inv.invoice_number)}
          {row('Date', fmtDate(inv.issued_at))}
          {row('For', inv.description || `${inv.plan_label} plan${inv.billing_cycle ? ` (${inv.billing_cycle})` : ''}`)}
          {inv.period_start && inv.period_end && row('Period', `${fmtDate(inv.period_start)} – ${fmtDate(inv.period_end)}`)}
          <hr />
          {row('Amount (excl. GST)', inrPaise(inv.base_paise))}
          {row(`GST (${inv.gst_rate_percent}%)`, inrPaise(inv.gst_paise))}
          {row('Total paid', <strong>{inrPaise(inv.total_paise)}</strong>)}
        </div>
      )}
    </div>
  );
}
