"use client";

export default function PageError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <main className="onboarding-frame">
      <div className="onboarding-brand"><strong>Recovery OS</strong></div>
      <section className="onboarding-card" aria-labelledby="page-error-title">
        <h1 id="page-error-title">We could not load this page</h1>
        <p>The service may be temporarily unavailable. Try loading it again. If you just submitted an action, check its status before submitting it again.</p>
        {error.digest && <p className="form-help">Support reference: {error.digest}</p>}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 20 }}>
          <button type="button" className="btn primary" onClick={() => retry()}>Try loading again</button>
          <a className="btn secondary" href="/login">Sign in</a>
          <a className="btn secondary" href="/">Return to homepage</a>
        </div>
      </section>
    </main>
  );
}
