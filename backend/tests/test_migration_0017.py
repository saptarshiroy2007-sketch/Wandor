"""Checks migration 0017 (plan_upgrades: upgrade-now with proration) on a throwaway SQLite DB:
the table/columns/constraints it adds match the models, the database refuses inconsistent or
duplicate rows, existing data is untouched, and downgrade/re-upgrade work.

Upgrades to 0018 (not head): the DB is built from the CURRENT models, so later revisions would re-create their tables.
Run from backend/:   python -m tests.test_migration_0017
Needs only SQLite. Like the 0015/0016 tests, the older chain is NOT replayed: the DB is built from
the models, the 0017 table is dropped, it is stamped 0016, then upgraded.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = Path(tempfile.mkdtemp()) / "mig17.db"
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
    model_cols = _cols(con, "plan_upgrades")
    assert model_cols, "models must define plan_upgrades"
    # pre-0017 state: no plan_upgrades, but real subscription + invoice data that must survive
    con.execute("DROP TABLE plan_upgrades")
    con.execute("INSERT INTO teachers (id,name,phone,hashed_password,phone_verified) VALUES ('t1','T','900','x',0)")
    con.execute("INSERT INTO subscriptions (id,teacher_id,plan,status,cancel_at_period_end) VALUES ('sub1','t1','basic','active',0)")
    con.execute("INSERT INTO invoices (id,invoice_number,subscription_id,kind,plan,base_paise,gst_rate_bps,gst_paise,"
                "total_paise,currency,issued_at) VALUES ('inv1','WND/2627/000001','sub1','subscription','basic',1000,"
                "1800,180,1180,'INR','2026-10-01 00:00:00')")
    con.commit()
    con.close()

    _alembic("stamp", "0016")
    _alembic("upgrade", "0018")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    # 1. the migrated schema has exactly the columns/nullability the models declare
    got = _cols(con, "plan_upgrades")
    assert set(got) == set(model_cols), set(got) ^ set(model_cols)
    for name, (_, notnull) in model_cols.items():
        assert got[name][1] == notnull, (name, "nullability differs from models")
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0018"
    assert con.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 1   # existing data untouched
    assert con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM plan_upgrades").fetchone()[0] == 0   # nothing is backfilled

    # 2. the database enforces the rules itself
    def ins(i="u1", order="order_1", pay=None, base=1000, gst=180, total=1180, sub="sub1"):
        con.execute(
            "INSERT INTO plan_upgrades (id,subscription_id,razorpay_order_id,razorpay_payment_id,from_plan,to_plan,"
            "billing_cycle,base_paise,gst_paise,total_paise,period_end,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, sub, order, pay, "basic", "pro", "monthly", base, gst, total, "2026-11-01 00:00:00", "2026-10-02 00:00:00"))

    ins()  # a consistent row is accepted; the server default fills status
    assert con.execute("SELECT status, renewal, applied_at FROM plan_upgrades").fetchone() == ("pending", None, None)
    for label, kw in [("total mismatch", dict(i="a", order="oa", total=1181)),
                      ("negative amount", dict(i="b", order="ob", base=-1000, total=-820)),
                      ("duplicate order", dict(i="c")),
                      ("unknown subscription", dict(i="d", order="od", sub="nope"))]:
        try:
            ins(**kw)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError(f"migrated schema accepted: {label}")
    ins(i="e", order="oe", pay="pay_1")
    try:
        ins(i="f", order="of", pay="pay_1")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("migrated schema accepted the same Razorpay payment twice")
    con.rollback()
    con.close()

    # 3. downgrade removes exactly the 0017 table; re-upgrading works
    _alembic("downgrade", "0016")
    con = sqlite3.connect(DB)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
    assert not names & {"plan_upgrades", "ix_plan_upgrades_subscription_id"}, names
    assert "invoices" in names and con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
    con.close()
    _alembic("upgrade", "0018")


def test_migration_0017_plan_upgrades():
    run()


if __name__ == "__main__":
    run()
    print("PASS  migration 0017: schema == models, constraints enforced, data untouched, downgrade, re-upgrade")
