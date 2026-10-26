"""Checks migration 0019 (platform admin + account access) on a throwaway SQLite DB: the new tables and
columns match the models, existing rows survive (new created_at stay NULL), `alembic check` is clean,
downgrade/re-upgrade work, and the two new settings parse as specified.

Run from backend/:   python -m pytest tests/test_migration_0019.py -q
Needs only SQLite. Like the 0015-0017 tests the older chain is NOT replayed: the DB is built from the
models, the 0019 additions are removed, it is stamped 0018, then upgraded.
"""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB = Path(tempfile.mkdtemp()) / "mig19.db"
ENV = {**os.environ, "DATABASE_URL": f"sqlite:///{DB}", "JWT_SECRET": "x"}
NEW_COLS = {
    "subscriptions": ["grace_until", "admin_banned", "admin_ban_reason", "admin_banned_at"],
    "teachers": ["created_at"],
    "students": ["created_at"],
}


def _alembic(*args):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=ENV, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout + r.stderr


def _cols(con, table):
    return {r[1]: (r[2].upper(), r[3]) for r in con.execute(f"PRAGMA table_info({table})")}  # name -> (type, notnull)


def run():
    subprocess.run([sys.executable, "-c",
                    "from app.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine)"],
                   cwd=BACKEND, env=ENV, check=True)
    con = sqlite3.connect(DB)
    model = {t: _cols(con, t) for t in ("platform_admins", "admin_audit_log", "subscriptions", "teachers", "students")}
    assert model["platform_admins"] and model["admin_audit_log"], "models must define both new tables"
    for t, cols in NEW_COLS.items():
        assert all(c in model[t] for c in cols), (t, "models must declare the new columns")
    # pre-0019 state
    con.execute("DROP TABLE admin_audit_log")
    con.execute("DROP TABLE platform_admins")
    for t, cols in NEW_COLS.items():
        for c in cols:
            con.execute(f"ALTER TABLE {t} DROP COLUMN {c}")
    con.execute("INSERT INTO teachers (id,name,phone,hashed_password,phone_verified) VALUES ('t1','T','900','x',0)")
    con.execute("INSERT INTO subscriptions (id,teacher_id,plan,status,cancel_at_period_end) VALUES ('sub1','t1','basic','active',0)")
    # backfill cases: an institute + an independent teacher WITHOUT rows, an institute WITH a row,
    # and a teacher inside an institute (must not get its own row)
    con.execute("INSERT INTO institutes (id,name,owner_phone,hashed_password,phone_verified) VALUES ('i1','I1','801','x',0)")
    con.execute("INSERT INTO institutes (id,name,owner_phone,hashed_password,phone_verified) VALUES ('i2','I2','802','x',0)")
    con.execute("INSERT INTO subscriptions (id,institute_id,plan,status,cancel_at_period_end) VALUES ('sub_i2','i2','pro','active',0)")
    con.execute("INSERT INTO teachers (id,name,phone,hashed_password,phone_verified) VALUES ('t2','T2','901','x',0)")
    con.execute("INSERT INTO teachers (id,institute_id,name,phone,hashed_password,phone_verified) VALUES ('t3','i2','T3','902','x',0)")
    con.commit()
    con.close()

    _alembic("stamp", "0018")
    _alembic("upgrade", "head")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=ON")
    # 1. migrated schema == models
    for t in model:
        got = _cols(con, t)
        assert set(got) == set(model[t]), (t, set(got) ^ set(model[t]))
        for name, (_, notnull) in model[t].items():
            assert got[name][1] == notnull, (t, name, "nullability differs from models")
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0019"
    # 2. existing data untouched; new created_at NULL; admin_banned defaults to false
    assert con.execute("SELECT created_at FROM teachers WHERE id='t1'").fetchone() == (None,)
    assert con.execute("SELECT admin_banned, grace_until FROM subscriptions WHERE id='sub1'").fetchone() == (0, None)
    # 2b. backfill: one free/active row for each owner lacking one; existing rows untouched; none for in-institute teachers
    def _free(col, oid):
        return con.execute(f"SELECT plan,status,admin_banned FROM subscriptions WHERE {col}=?", (oid,)).fetchall()
    assert _free("institute_id", "i1") == [("free", "active", 0)]
    assert _free("teacher_id", "t2") == [("free", "active", 0)]
    assert _free("institute_id", "i2") == [("pro", "active", 0)]
    assert _free("teacher_id", "t1") == [("basic", "active", 0)]
    assert _free("teacher_id", "t3") == []
    assert con.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 4
    # 3. constraints
    con.execute("INSERT INTO platform_admins (id,phone,hashed_password,created_at) VALUES ('a1','111','x','2026-10-01')")
    try:
        con.execute("INSERT INTO platform_admins (id,phone,hashed_password,created_at) VALUES ('a2','111','x','2026-10-01')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("duplicate admin phone accepted")
    con.execute("INSERT INTO admin_audit_log (id,admin_id,action,subscription_id,created_at) VALUES ('l1','a1','ban','sub1','2026-10-01')")
    try:
        con.execute("INSERT INTO admin_audit_log (id,admin_id,action,subscription_id,created_at) VALUES ('l2','nope','ban','sub1','2026-10-01')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("audit row with unknown admin accepted")
    con.rollback()
    con.close()

    # 4. alembic check is clean
    # (On SQLite every UUID column reflects as NUMERIC, so check reports a modify_type for every id/FK of
    # every table, old and new. That noise is inherent to SQLite; what matters is that nothing else
    # - no add/remove table/column/index/constraint, no nullability change - is reported. The strict
    # "No new upgrade operations detected" check is the Postgres one, see pg_alembic.sh.)
    r = subprocess.run([sys.executable, "-m", "alembic", "check"], cwd=BACKEND, env=ENV, capture_output=True, text=True)
    ops = set(re.findall(r"\('([a-z]+_[a-z_]+)',", r.stdout + r.stderr))
    assert ops <= {"modify_type"}, (ops, r.stdout[-2000:])
    assert "NUMERIC(), UUID" in (r.stdout + r.stderr) or "No new upgrade operations" in (r.stdout + r.stderr)

    # 5. downgrade removes exactly the 0019 additions; re-upgrade works
    _alembic("downgrade", "0018")
    con = sqlite3.connect(DB)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not names & {"platform_admins", "admin_audit_log"}, names
    for t, cols in NEW_COLS.items():
        assert not set(cols) & set(_cols(con, t)), t
    assert con.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 4  # backfilled rows are kept
    con.close()
    _alembic("upgrade", "head")
    con = sqlite3.connect(DB)
    assert con.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 4  # re-running adds none
    con.close()


def test_migration_0019_platform_admin_and_access():
    run()


def test_new_settings_parse(monkeypatch):
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    os.environ.setdefault("JWT_SECRET", "x")
    from app.database import Settings
    base = dict(database_url="sqlite://", jwt_secret="x")
    monkeypatch.delenv("ENFORCEMENT_START", raising=False)
    monkeypatch.delenv("LIMITED_GRACE_DAYS", raising=False)
    s = Settings(_env_file=None, **base)
    assert s.enforcement_start is None and s.limited_grace_days == 15
    for raw, want in [("2026-11-01", datetime(2026, 11, 1)),
                      ("2026-11-01T10:30:00", datetime(2026, 11, 1, 10, 30)),
                      ("2026-11-01T10:30:00Z", datetime(2026, 11, 1, 10, 30)),
                      ("2026-11-01T16:00:00+05:30", datetime(2026, 11, 1, 10, 30)),
                      ("", None)]:
        monkeypatch.setenv("ENFORCEMENT_START", raw)
        got = Settings(_env_file=None, **base).enforcement_start
        assert got == want and (got is None or got.tzinfo is None), (raw, got)
    monkeypatch.setenv("LIMITED_GRACE_DAYS", "7")
    assert Settings(_env_file=None, **base).limited_grace_days == 7


if __name__ == "__main__":
    run()
    print("PASS  migration 0019")
