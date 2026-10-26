import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import '../landing.css';

/* ── Signature: live roll call ────────────────────────────────────────────────
   40 squares = one batch. Filled = present, outline = absent. Two flip every
   beat and the counter follows. It is the product's real job drawn as a block. */
const SEATS = 40;
const START_ABSENT = [3, 9, 14, 22, 27, 31, 36];

function RollCall({ animate }: { animate: boolean }) {
  const [absent, setAbsent] = useState<Set<number>>(() => new Set(START_ABSENT));

  useEffect(() => {
    if (!animate) return;
    const id = window.setInterval(() => {
      setAbsent((prev) => {
        const next = new Set(prev);
        for (let k = 0; k < 2; k++) {
          const i = Math.floor(Math.random() * SEATS);
          if (next.has(i)) next.delete(i);
          else next.add(i);
        }
        return next;
      });
    }, 900);
    return () => window.clearInterval(id);
  }, [animate]);

  const present = SEATS - absent.size;

  return (
    <figure className="lp-roll" aria-label={`Sample roll call: ${present} of ${SEATS} present`}>
      <figcaption className="lp-roll-head">
        <span>Roll call</span>
        <span>Sample batch</span>
      </figcaption>
      <div className="lp-roll-grid" aria-hidden="true">
        {Array.from({ length: SEATS }, (_, i) => (
          <i key={i} className={absent.has(i) ? 'is-absent' : ''} style={{ ['--i' as string]: i }} />
        ))}
      </div>
      <div className="lp-roll-foot" aria-hidden="true">
        <b>{present}</b>
        <span>/ {SEATS} present</span>
      </div>
    </figure>
  );
}

const MODULES = [
  {
    n: '01',
    when: 'Before class',
    title: 'Schedule',
    body: 'Put a class on the calendar once. Students and parents see it, and a cancellation reaches them the moment you make it.',
    glyph: 'g-circle',
    cls: 'm-ivory m-a',
  },
  {
    n: '02',
    when: 'During class',
    title: 'Attendance',
    body: 'One tap per student. Absences add up per batch, so you see who is slipping before the parents call you.',
    glyph: 'g-square',
    cls: 'm-ink m-b',
  },
  {
    n: '03',
    when: 'After class',
    title: 'Tests',
    body: 'Write multiple-choice questions or upload a paper. Students take it on their phones and results land in your list.',
    glyph: 'g-tri',
    cls: 'm-red m-c',
  },
  {
    n: '04',
    when: 'Month end',
    title: 'Fees',
    body: 'See who has paid and who has not. Collect online, and every payment gets a receipt without you typing one.',
    glyph: 'g-bars',
    cls: 'm-grey m-d',
  },
];

const ROLES = [
  {
    name: 'Teacher',
    text: 'You run your own classes. Your batches, your students, your fees.',
    login: '/login',
    signup: '/teacher-signup',
    signupLabel: 'Create teacher account',
  },
  {
    name: 'Institute',
    text: 'You run a centre with several teachers. Add them, assign batches, watch the whole roll.',
    login: '/institute-login',
    signup: '/institute-signup',
    signupLabel: 'Register institute',
  },
  {
    name: 'Student & parent',
    text: 'Your teacher adds you. See the timetable, take tests, check attendance and pay fees.',
    login: '/student-login',
    signup: '/parent-login',
    signupLabel: 'Parent login',
  },
];

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduced;
}

export default function Landing() {
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const [ready, setReady] = useState(false);

  // Scroll-triggered reveal. Hidden state only applies once `ready` is set,
  // so nothing stays invisible if the observer never fires.
  useEffect(() => {
    setReady(true);
    const els = root.current?.querySelectorAll<HTMLElement>('[data-reveal]');
    if (!els) return;
    if (reduced || !('IntersectionObserver' in window)) {
      els.forEach((e) => e.classList.add('in'));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add('in');
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -8% 0px' }
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [reduced]);

  return (
    <div ref={root} className={`lp${ready ? ' is-ready' : ''}${reduced ? ' is-still' : ''}`}>
      <a className="lp-skip" href="#main">Skip to content</a>

      {/* ── NAV ─────────────────────────────────────────────── */}
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-in">
          <Link to="/" className="lp-logo" aria-label="Wandor home">
            <span className="lp-logo-mark" aria-hidden="true">W</span>
            <span className="lp-logo-word">Wandor</span>
          </Link>
          <nav className="lp-nav-links" aria-label="Sections">
            <a href="#week">The week</a>
            <a href="#who">Who it's for</a>
          </nav>
          <Link to="/enter" className="lp-btn lp-btn-ink lp-btn-sm">Log in</Link>
        </div>
      </header>

      <main id="main">
        {/* ── HERO ──────────────────────────────────────────── */}
        <section className="lp-hero">
          <div className="lp-gridlines" aria-hidden="true" />
          <div className="lp-hero-circle" aria-hidden="true" />
          <div className="lp-hero-diag" aria-hidden="true" />
          <div className="lp-halftone" aria-hidden="true" />

          <div className="lp-wrap lp-hero-in">
            <p className="lp-label lp-hero-label">
              <span className="lp-dot" /> Coaching management · India
            </p>

            <h1 className="lp-h1" aria-label="Run the room.">
              <span className="lp-line"><span>Run the</span></span>
              <span className="lp-line">
                <span>
                  R<em className="lp-o lp-o-fill" />
                  <em className="lp-o lp-o-ring" />M.
                </span>
              </span>
            </h1>

            <div className="lp-hero-lower">
              <p className="lp-lede">
                Wandor schedules your classes, takes attendance, sets tests and collects fees.
                One app for the teacher, the student and the parent.
              </p>
              <div className="lp-cta-row">
                <Link to="/teacher-signup" className="lp-btn lp-btn-red">Start as a teacher</Link>
                <Link to="/institute-signup" className="lp-btn lp-btn-line">Register an institute</Link>
              </div>
            </div>

            <RollCall animate={!reduced} />

            <span className="lp-vert" aria-hidden="true">Schedule — Attendance — Tests — Fees</span>
          </div>
        </section>

        {/* ── TICKER ────────────────────────────────────────── */}
        <div className="lp-ticker" aria-hidden="true">
          <div className="lp-ticker-track">
            {Array.from({ length: 2 }).map((_, k) => (
              <div className="lp-ticker-set" key={k}>
                {['Schedule', 'Attendance', 'Tests', 'Fees', 'Receipts', 'Parents in the loop'].map((t) => (
                  <span key={t}>
                    {t}
                    <i />
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* ── MANIFESTO ─────────────────────────────────────── */}
        <section className="lp-manifesto">
          <div className="lp-wrap lp-manifesto-in">
            <p className="lp-label lp-label-light" data-reveal>Position</p>
            <p className="lp-manifesto-text" data-reveal>
              A register, a WhatsApp group and a fee notebook is <mark>three jobs</mark> pretending to be
              one system. Wandor makes it one.
            </p>
          </div>
        </section>

        {/* ── THE WEEK ──────────────────────────────────────── */}
        <section className="lp-week" id="week">
          <div className="lp-wrap">
            <header className="lp-sec-head" data-reveal>
              <p className="lp-label">The teaching cycle</p>
              <h2 className="lp-h2">Four jobs.<br />One loop.</h2>
            </header>

            <div className="lp-modules">
              {MODULES.map((m) => (
                <article key={m.n} className={`lp-mod ${m.cls}`} data-reveal>
                  <span className="lp-mod-n" aria-hidden="true">{m.n}</span>
                  <span className={`lp-glyph ${m.glyph}`} aria-hidden="true"><i /><i /><i /></span>
                  <p className="lp-label lp-mod-when">{m.when}</p>
                  <h3 className="lp-mod-title">{m.title}</h3>
                  <p className="lp-mod-body">{m.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ── WHO ───────────────────────────────────────────── */}
        <section className="lp-who" id="who">
          <div className="lp-wrap">
            <header className="lp-sec-head lp-sec-head-r" data-reveal>
              <p className="lp-label">Pick your door</p>
              <h2 className="lp-h2">Three<br />ways in.</h2>
            </header>

            <ul className="lp-roles">
              {ROLES.map((r) => (
                <li key={r.name} className="lp-role" data-reveal>
                  <h3 className="lp-role-name">{r.name}</h3>
                  <p className="lp-role-text">{r.text}</p>
                  <div className="lp-role-links">
                    <Link to={r.login} className="lp-arrow">Log in</Link>
                    <Link to={r.signup} className="lp-arrow lp-arrow-quiet">{r.signupLabel}</Link>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ── CTA ───────────────────────────────────────────── */}
        <section className="lp-cta">
          <div className="lp-cta-cut" aria-hidden="true" />
          <div className="lp-wrap lp-cta-in">
            <h2 className="lp-cta-h" data-reveal>
              Open<br />the register.
            </h2>
            <div className="lp-cta-side" data-reveal>
              <p>Set up your first batch in a few minutes. No paper, no spreadsheet, no group chat to scroll back through.</p>
              <div className="lp-cta-row">
                <Link to="/teacher-signup" className="lp-btn lp-btn-ink">Start as a teacher</Link>
                <Link to="/institute-signup" className="lp-btn lp-btn-ivory">Register an institute</Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ── FOOTER ──────────────────────────────────────────── */}
      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-in">
          <nav className="lp-foot-links" aria-label="Log in">
            <Link to="/login">Teacher</Link>
            <Link to="/institute-login">Institute</Link>
            <Link to="/student-login">Student</Link>
            <Link to="/parent-login">Parent</Link>
          </nav>
          <p className="lp-label lp-label-light">© {new Date().getFullYear()} Wandor</p>
        </div>
        <div className="lp-foot-word" aria-hidden="true">WANDOR</div>
      </footer>
    </div>
  );
}
