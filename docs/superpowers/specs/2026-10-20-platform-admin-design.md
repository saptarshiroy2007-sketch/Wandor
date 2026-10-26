# Wandor platform admin: design

Date: 2026-10-20. Written for the two founders. Everything under "Decided" came from the founder; everything under "Builder's calls" is a default chosen by the writer and can be overridden.

## Intent

The two founders want one place to see whether Wandor, as a business, is healthy: how many people pay for a plan, how many users exist, and how much money has come in. They also want a lever for dealing with accounts that stop paying: give them more time, and when time runs out, switch them off. The panel is a money-and-growth dashboard first. It is not a tool for digging into individual classrooms.

## Who and how

- Two users, the co-founders, with identical full access. No roles or permission levels (a support role may come later; not now).
- A separate login that is not part of the teacher, owner, student or parent screens.

## Dashboard (decided)

Six numbers on the first screen:

1. Paying users: teachers and institute owners on a paid plan.
2. Total users: every type (teachers, institute owners, students, parents).
3. Users gained this week.
4. Total revenue.
5. Revenue this week.
6. Revenue this month.

Below them, a list of every paying account: name, kind (independent teacher or institute), plan, status (active, grace, banned), and when its current period ends. From this list a founder can extend that account's grace.

## Account lifecycle (decided)

For an account that pays for a plan:

1. **Active**: paid up, everything works.
2. **Grace**: the paid period has ended without payment. Attendance, tests and analytics are switched off for the account. The rest keeps working. A founder can extend the grace window from the panel.
3. **Banned**: grace has ended. The account is locked.

Paying at any stage, including while banned for non-payment, returns the account to Active automatically. No approval step.

## Manual ban and lift (decided)

Separately from the payment lifecycle, a founder can ban a paying account (an independent teacher or an institute owner) by hand and lift that ban later, from the account list. Individual students, parents, and teachers inside an institute are out of scope.

- A manual ban is its own flag, with a reason and who set it and when. It locks the account exactly like a payment ban does.
- **Paying does not lift a manual ban.** Only a founder lifting it does. (Otherwise a banned abuser could pay their way back in.)
- Lifting a manual ban puts the account back to whatever its payment state says right now (Active, grace or banned for non-payment).
- Every ban and lift goes in the same audit trail as grace extensions.

## Decisions the writer made (builder's calls)

- **Stack:** build on what exists: the FastAPI backend and the same React web app. The admin lives at its own route (for example `/admin`).
- **Admin identity:** a new `platform_admins` table (phone, hashed password) and a new token role `platform_admin`, kept entirely separate from teacher, student, parent and `institute_admin` tokens so no existing token can reach admin endpoints and vice versa. No public signup: admins are created by a command-line script run on the server. Login is rate limited like the other login endpoints.
- **Revenue** means plan payments actually collected, taken from the existing `invoices` table, shown in rupees. Student fee payments (which pass through the app) are not included. GST is shown separately and not counted as revenue.
- **Paying users** excludes accounts still on a free trial and accounts on the free plan.
- **"This week"** means the last 7 days, not Monday to Sunday. "This month" means the calendar month in Asia/Kolkata.
- **Audit trail:** every grace extension is recorded with who did it, when, the old and new end dates, and an optional note.
- **Accounts that are on the free tier, or whose trial already ended, when this ships** have no free plan to fall back to, so they follow the same path as everyone else: a 15-day grace that starts on release day, then ban. (Writer's call: the founder said such accounts end up banned; starting their clock on release day means nobody is banned with zero warning. The builder should record the release date.)
- **What "switched off" means in grace:** no new attendance can be marked, no new tests can be created or started, and the analytics views are hidden. Existing data stays readable and a test already in progress can still be submitted. Students and parents can still see their past attendance and results.
- **A banned owner can still log in** and sees only the Billing page, because paying is how an account comes back. A banned independent teacher is the same (their own Billing page only). Who else under an institute is locked is a founder question below.
- **When grace starts:** at the end of the paid period, after the existing short full-features buffer (today `BILLING_GRACE_DAYS`, 3 days) that protects customers whose renewal webhook is late. Limited-features grace begins after that buffer.
- **Extending grace** sets an absolute "ban date" chosen by the founder; it can only move the date later. It works on accounts in grace or banned (a banned account returns to limited-features grace until the new date). It does not restore the switched-off features; only payment does.
- **"Paying users" counts accounts, not people** (an institute with ten teachers is 1), and counts accounts with a paid plan that are Active or in Grace, not Banned and not trials. The account list shows the same set plus banned ones, clearly marked, so the headline number and the list can be reconciled.
- **Extending grace** stores a per-account "grace until" date that overrides the global default for that account only.

## How it fits what exists today (findings from reading the code)

- Entitlement is decided in one place: `effective_plan()` in `backend/app/services/subscriptions.py`. Today, a lapsed paid account keeps its full paid plan for `BILLING_GRACE_DAYS` (default 3) and then silently drops to the free plan. There is no limited-features stage and no ban. This design changes that behaviour for lapsed paid accounts.
- Attendance, tests and analytics are currently not gated by plan at all; every plan has them. The grace limitation is new gating.
- Subscriptions belong to either an institute (covers its teachers, students and parents) or an independent teacher (covers their students and parents). Status values today: trialing, active, past_due, cancelled, expired.
- Revenue data already exists in `invoices` (base, GST and total in integer paise).
- Razorpay webhooks already update subscription status and are the path by which "paying brings it back" will happen.

## Goals

- Founders can answer "are we growing and are we getting paid" in one glance.
- Lapsed accounts move through grace and ban without a founder doing anything, and a founder can intervene by extending grace.
- A payment always restores an account on its own.

## Non-goals

- Browsing individual classes, students, tests or fee records.
- Editing a customer's data, impersonating a customer, or issuing refunds.
- Multiple admin roles, admin signup screens, email or WhatsApp nudges to late payers.
- Charts and trend graphs beyond the six numbers (can follow later).

## Anti-goals (would make this a failure even if it technically works)

- A banned or grace-limited account that gets locked wrongly, for example a paying customer cut off because a webhook arrived late.
- Any customer-facing token or screen being able to reach admin data.
- Revenue numbers that disagree with the invoices.

## Constraints

- Postgres in production, SQLite in dev; migrations must work on both (the project's existing rule is that Alembic works on an empty Postgres).
- Money is integer paise everywhere.
- Timestamps are stored naive UTC and sent with a trailing `Z`; dashboard windows are computed in Asia/Kolkata.
- Existing billing tests (74) must keep passing.

## Left to the builder

- Exact table and column names, endpoint paths and response shapes.
- The visual layout of the dashboard and account list.
- How the grace and ban state is computed (stored versus derived) as long as it lives in one place next to `effective_plan()`.
- Whether the limited-feature checks reuse the existing plan "features" mechanism.

## Founder answers (2026-10-21)

1. When an institute is banned, **everyone under it is locked**: teachers, students and parents. (The owner can still reach Billing to pay.)
2. **There is no free plan going forward.** The lifecycle is paid plan -> grace -> ban. The free tier in the code today (25 students, 1 teacher) is removed from entitlement, and a trial that ends unpaid goes into grace then ban. Founder reasoning on existing accounts: an institute with 100 students can't drop to a free plan, so it ends up banned.
3. **Limited-features grace lasts 15 days**, starting after the existing 3-day full-features buffer.

4. **Manual ban applies to paying accounts only**: an independent teacher or an institute owner. Founders cannot ban or lift individual students, parents, or teachers inside an institute; managing those people is up to the teachers and institute owners. Banning an institute still locks everyone under it (answer 1).

## Open questions for the founders

None.
