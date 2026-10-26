"""Checks migration 0016 (subscription invoices + invoice numbering) on a throwaway SQLite DB:
the tables/columns/constraints it adds match the models, the database refuses inconsistent
invoices, existing data is untouched, and downgrade/re-upgrade work.

Run from backend/:   python -m tests.test_migration_0016
Needs only SQLite. Like the 0015 test, the older chain is NOT replayed: the DB is built from the
models, the 0016 tables are dropped, it is stamped 0015, then upgraded.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = Path(tempfile.mkdtemp()) / "mig16.db"
ENV = {**os.environ, "DATABASE_URL": f"sqlite:///{DB}", "JWT_SECRET": "x"}


def _alembic(*args):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=ENV, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout


def _cols(con, table):
    return {r[1]: (r[2].upper(), r[3]) for r in con.execute(f"PRAGMA table_info({table})")}  # name -> (type, notnull)


def run():
    subprocess.run([sys.executable, "-c",
                    "from app.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine)"],
                   cwd=BACKEND, env=ENV, check=True)
    con = sqlite3.connect(DB)
    model_cols = {t: _cols(con, t) for t in ("invoices", "invoice_counters")}
    assert model_cols["invoices"], "models must define invoices"
    # pre-0016 state: no invoice tables, but real subscription data that must survive
    con.execute("DROP TABLE plan_upgrades")  # 0017's table: this test upgrades to head, which re-creates it
    con.execute("DROP TABLE invoices")
    con.execute("DROP TABLE invoice_counters")
    con.execute("INSERT INTO teachers (id,name,phone,hashed_password,phone_verified) VALUES ('t1','T','900','x',0)")
    con.execute("INSERT INTO subscriptions (id,teacher_id,plan,status,cancel_at_period_end) VALUES ('sub1','t1','basic','active',0)")
    con.commit()
    con.close()

    _alembic("stamp", "0015")
    _alembic("upgrade", "0018")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    # 1. the migrated schema has exactly the columns/nullability the models declare
    for t in ("invoices", "invoice_counters"):
        got = _cols(con, t)
        assert set(got) == set(model_cols[t]), (t, set(got) ^ set(model_cols[t]))
        for name, (_, notnull) in model_cols[t].items():
            assert got[name][1] == notnull, (t, name, "nullability differs from models")
    # upgraded past 0015 (head moves on with later migrations, so don't pin it to 0016)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] != "0015"
    assert con.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 1  # existing data untouched
    assert con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0       # nothing is backfilled

    # 2. the database enforces the rules itself
    def ins(num="WND/2627/000001", total=1180, base=1000, gst=180, pay=None, sub="sub1"):
        con.execute(
            "INSERT INTO invoices (id,invoice_number,subscription_id,plan,base_paise,gst_rate_bps,gst_paise,"
            "total_paise,razorpay_payment_id,issued_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (num, num, sub, "basic", base, 1800, gst, total, pay, "2026-10-01 00:00:00"))

    ins()  # a consistent invoice is accepted; server defaults fill kind/currency
    assert con.execute("SELECT kind, currency FROM invoices").fetchone() == ("subscription", "INR")
    for label, kw in [("total mismatch", dict(num="A", total=1181)),
                      ("negative amount", dict(num="B", base=-1000, total=-820)),
                      ("duplicate number", dict()),
                      ("unknown subscription", dict(num="C", sub="nope"))]:
        try:
            ins(**kw)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(f"migrated schema accepted: {label}")
    ins(num="D", pay="pay_1")
    try:
        ins(num="E", pay="pay_1")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("migrated schema accepted the same Razorpay payment twice")
    con.rollback()
    con.close()

    # 3. downgrade removes exactly the 0016 tables; re-upgrading works
    _alembic("downgrade", "0015")
    con = sqlite3.connect(DB)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
    assert not names & {"invoices", "invoice_counters", "ix_invoices_subscription_id"}, names
    assert con.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 1
    con.close()
    _alembic("upgrade", "0018")


def test_migration_0016_invoices():
    run()


if __name__ == "__main__":
    run()
    print("PASS  migration 0016: schema == models, constraints enforced, data untouched, downgrade, re-upgrade")
