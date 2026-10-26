"""Checks migration 0015 (fee payment ledger) on a throwaway SQLite DB: the schema it
adds, and that existing paid fees are backfilled into the ledger so the cached totals
and the ledger agree from the first request after upgrading.

Run from backend/:   python -m tests.test_migration_0015
Needs only SQLite (no Postgres, no network). The older migration chain is NOT replayed -
the DB is built from the models, rolled back to the pre-0015 shape, stamped 0014, then
upgraded - because that chain doesn't run on an empty database (see HANDOFF.md).
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = Path(tempfile.mkdtemp()) / "mig.db"
ENV = {**os.environ, "DATABASE_URL": f"sqlite:///{DB}", "JWT_SECRET": "x"}


def _alembic(*args):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=ENV, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout


def run():
    # 1. build tables from the models, then undo exactly what 0015 (and later 0016, 0017) add
    subprocess.run([sys.executable, "-c",
                    "from app.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine)"],
                   cwd=BACKEND, env=ENV, check=True)
    con = sqlite3.connect(DB)
    # the models now also define the 0016 tables; this test stamps 0014 and upgrades to head, so
    # 0016 will re-create them - drop them here exactly like 0015's own additions
    con.execute("DROP TABLE plan_upgrades")  # (and 0017's)
    con.execute("DROP TABLE invoices")
    con.execute("DROP TABLE invoice_counters")
    con.execute("DROP TABLE fee_payments")
    con.execute("ALTER TABLE fee_records DROP COLUMN allow_partial")

    # 2. pre-0015 data: online-paid, manual-paid, unpaid, manual with no mode set, flagged duplicate
    con.execute("INSERT INTO institutes (id,name,owner_phone,hashed_password,phone_verified) VALUES ('i1','Inst','900','x',0)")
    con.execute("INSERT INTO students (id,institute_id,name,phone) VALUES ('s1','i1','Stu','901')")
    rows = [
        # id, due, paid, order, payment, mode, is_paid, dup
        ("f_online", 1500.0, 1500.0, "order_1", "pay_1", "online", 1, None),
        ("f_manual", 800.0, 800.0, None, None, "manual", 1, None),
        ("f_unpaid", 500.0, 0.0, "order_open", None, None, 0, None),
        ("f_nomode", 300.0, 300.0, None, None, None, 1, None),
        ("f_dup", 400.0, 400.0, "order_2", "pay_2", "online", 1, "pay_2_extra"),
    ]
    for fid, due, paid, order, pay, mode, is_paid, dup in rows:
        con.execute(
            "INSERT INTO fee_records (id,student_id,amount_due,amount_paid,due_date,razorpay_order_id,"
            "razorpay_payment_id,is_paid,payment_mode,duplicate_payment_id,paid_at,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, "s1", due, paid, "2026-09-01 00:00:00", order, pay, is_paid, mode, dup,
             "2026-09-02 10:00:00" if is_paid else None, "2026-08-30 09:00:00"))
    con.commit()
    con.close()

    # 3. stamp as 0014 and upgrade
    _alembic("stamp", "0014")
    _alembic("upgrade", "0018")

    con = sqlite3.connect(DB)
    cols = {r[1]: r for r in con.execute("PRAGMA table_info(fee_records)")}
    assert "allow_partial" in cols and cols["allow_partial"][3] == 1, "allow_partial must exist and be NOT NULL"
    assert [r[0] for r in con.execute("SELECT allow_partial FROM fee_records")] == [0] * 5, "existing fees stay pay-in-full"

    pays = {r[0]: r[1:] for r in con.execute(
        "SELECT fee_record_id, amount_paise, refunded_paise, mode, status, razorpay_order_id, razorpay_payment_id, paid_at "
        "FROM fee_payments")}
    assert set(pays) == {"f_online", "f_manual", "f_nomode", "f_dup"}, pays.keys()  # unpaid fee: no row
    assert pays["f_online"][:6] == (150000, 0, "online", "paid", "order_1", "pay_1")
    assert pays["f_manual"][:6] == (80000, 0, "manual", "paid", None, None)
    assert pays["f_nomode"][2] == "manual"          # no mode + no Razorpay id = hand-recorded
    assert pays["f_dup"][0] == 40000                 # only the genuinely-applied payment is in the ledger
    assert all(p[6] == "2026-09-02 10:00:00" for p in pays.values())  # paid_at carried over

    # 4. the ledger agrees with every fee's cached total, and the duplicate flag survives
    for fid, paid in con.execute("SELECT id, amount_paid FROM fee_records"):
        net = con.execute("SELECT COALESCE(SUM(amount_paise - refunded_paise),0) FROM fee_payments "
                          "WHERE fee_record_id=? AND status='paid'", (fid,)).fetchone()[0]
        assert round(paid * 100) == net, (fid, paid, net)
    assert con.execute("SELECT duplicate_payment_id FROM fee_records WHERE id='f_dup'").fetchone()[0] == "pay_2_extra"
    # upgraded past 0014 (head moves on with later migrations, so don't pin it to 0015)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] != "0014"
    con.close()

    # 5. downgrade removes exactly what 0015 added, and re-upgrading works
    _alembic("downgrade", "0014")
    con = sqlite3.connect(DB)
    assert not con.execute("SELECT name FROM sqlite_master WHERE name='fee_payments'").fetchall()
    assert "allow_partial" not in [r[1] for r in con.execute("PRAGMA table_info(fee_records)")]
    con.close()
    _alembic("upgrade", "0018")


def test_migration_0015_backfills_ledger():
    run()


if __name__ == "__main__":
    run()
    print("PASS  migration 0015: schema, backfill, ledger == cached totals, downgrade, re-upgrade")
