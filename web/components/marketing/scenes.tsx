import { StatusBadge } from "@/components/epic1/status-badge";
import { demo } from "./demo-data";

export function Badge({ children, tone = "neutral" }: { children: string; tone?: "good" | "warn" | "bad" | "neutral" }) {
  return <span className={`m-badge m-badge-${tone}`}><StatusBadge value={children}/></span>;
}

export function ProductFrame({ title, children, large = false }: { title: string; children: React.ReactNode; large?: boolean }) {
  return <div className={`m-product-frame${large ? " m-product-large" : ""}`}>
    <div className="m-product-bar"><span className="m-product-brand"><span className="m-mark" aria-hidden="true">r.</span> Recovery OS</span><span className="m-demo-label">SYNTHETIC DEMO</span></div>
    <div className="m-product-context"><span>{demo.advertiser}</span><span>Google Ads / Search</span></div>
    <div className="m-product-content"><div className="m-product-heading"><span>{title}</span><span className="m-product-dot" aria-hidden="true"/></div>{children}</div>
  </div>;
}

export function SearchScene() {
  return <ProductFrame title="Search Intelligence">
    <div className="m-scene-meta"><span>{demo.campaign}</span><span>{demo.period}</span></div>
    <div className="m-search-summary"><div><span>Observed candidate exposure</span><strong>{demo.candidate}<small>USD</small></strong></div><Badge tone="warn">Review required</Badge></div>
    <div className="m-query-row m-query-row-head"><span>Search term</span><span>Evidence</span></div>
    <div className="m-query-row"><strong>{demo.query}</strong><Badge tone="warn">Training intent</Badge></div>
    <div className="m-query-row"><strong>{demo.protectedQuery}</strong><Badge tone="good">Protected</Badge></div>
    <div className="m-coverage"><div><span>Visible Search spend</span><strong>{demo.coverage}%</strong></div><div className="m-coverage-bar"><span style={{width:`${demo.coverage}%`}}/></div><p>The other 22% is unobserved. No waste claim.</p></div>
  </ProductFrame>;
}

export function TruthScene() {
  return <ProductFrame title="Business Truth">
    <div className="m-scene-meta"><span>Published {demo.truthVersion}</span><code>{demo.fingerprint}</code></div>
    <dl className="m-truth-list"><div><dt>We sell</dt><dd>Residential roof repair<br/>Roof replacement</dd></div><div><dt>We do not sell</dt><dd>Training · jobs · DIY materials</dd></div><div><dt>Service area</dt><dd>Austin, Texas</dd></div><div><dt>Business outcome</dt><dd>Roofing enquiry <small>Qualification not independently measured</small></dd></div><div><dt>Protected query</dt><dd><Badge tone="good">roofing company</Badge></dd></div></dl>
    <div className="m-scene-foot">Immutable version · Approval bound to current truth</div>
  </ProductFrame>;
}

export function MeasurementScene() {
  return <ProductFrame title="Measurement Integrity">
    <div className="m-measure-head"><div><span>Account assessment</span><h3>What counts as success?</h3></div><Badge tone="warn">constrained</Badge></div>
    <div className="m-measure-row"><div><strong>Roofing enquiry form</strong><small>Confirmed primary outcome mapping</small></div><span>Recorded lead</span></div>
    <div className="m-measure-row"><div><strong>Contact page view</strong><small>Supporting signal · marked primary in Google</small></div><Badge tone="warn">review role</Badge></div>
    <div className="m-measure-row"><div><strong>Qualified customer</strong><small>No independent downstream evidence</small></div><Badge>unknown</Badge></div>
    <div className="m-scene-warning">Enquiry mapping confirmed. The page-view goal needs review.</div>
  </ProductFrame>;
}

export function ActionScene({ blocked = false, applied = false }: { blocked?: boolean; applied?: boolean }) {
  return <ProductFrame title="Action Center">
    <div className="m-scene-meta"><span>Exact ad-group negative</span><Badge tone={blocked ? "bad" : applied ? "good" : "warn"}>{blocked ? "blocked" : applied ? "configuration verified" : "awaiting approval"}</Badge></div>
    <div className="m-negative">[{blocked ? demo.protectedQuery : demo.query}]</div>
    <dl className="m-action-facts"><div><dt>Ad group</dt><dd>{demo.adGroup}</dd></div><div><dt>Business Truth</dt><dd>{demo.truthVersion} · {blocked ? "Protected commercial query" : "Confirmed non-offer"}</dd></div><div><dt>Protected-query collision</dt><dd className={blocked ? "m-risk-text" : "m-verified-text"}>{blocked ? "1 · Action blocked" : "0 · No collision"}</dd></div><div><dt>Provider state</dt><dd>{applied ? "Exact resource confirmed" : "No account change"}</dd></div></dl>
    <div className={blocked ? "m-scene-warning m-scene-danger" : "m-scene-foot"}>{blocked ? "Protected intent takes precedence over a negative proposal." : applied ? "Rollback identity retained · Financial verification pending" : "Evidence → human approval → validation → read-back"}</div>
  </ProductFrame>;
}

export function RecoveryScene() {
  return <ProductFrame title="Recovery Center">
    <div className="m-scene-meta"><span>After simulated application</span><span>USD · Non-additive</span></div>
    <div className="m-money-row"><span>Current observed candidate<small>Latest completed analysis · not refreshed</small></span><strong>{demo.candidate}</strong></div>
    <div className="m-money-row"><span>Historical acted-on exposure<small>{demo.period}</small></span><strong>{demo.candidate}</strong></div>
    <div className="m-money-row"><span>Projected prevention<small>{demo.projection} · 30-day run-rate estimate</small></span><strong>{demo.projected}</strong></div>
    <div className="m-money-row"><span>Post-action observed query spend<small>No observation collected · not measured zero</small></span><strong>{demo.observed}</strong></div>
    <div className="m-money-row m-money-verified"><span>Verified recovery<small>Causal evidence pending</small></span><strong>{demo.verified}</strong></div>
    <div className="m-scene-foot">Configuration verified does not mean savings verified.</div>
  </ProductFrame>;
}

export function MonitoringScene() {
  return <ProductFrame title="Monitoring & Alerts"><div className="m-scene-meta"><span>Account attention queue</span><span>After sync</span></div><div className="m-monitor-row"><span className="m-alert-dot"/><div><strong>Measurement constrained</strong><small>Review conversion-action mapping</small></div><Badge tone="warn">review</Badge></div><div className="m-monitor-row"><span className="m-alert-dot m-alert-neutral"/><div><strong>Data freshness</strong><small>Check the latest completed sync</small></div><Badge>observed</Badge></div><div className="m-monitor-row"><span className="m-alert-dot m-alert-red"/><div><strong>Provider effect uncertain</strong><small>Illustration of a reconciliation alert</small></div><Badge tone="bad">hold</Badge></div><div className="m-scene-foot">Evaluated after sync or on request. No silent replay.</div></ProductFrame>;
}

export function ReportScene() {
  return <ProductFrame title="Reports"><div className="m-report-sheet"><span className="m-report-kicker">RECOVERY EVIDENCE / DEMO</span><h3>{demo.advertiser}</h3><p>Change Impact Report · October 2026</p><div className="m-report-rule"/><dl><div><dt>Generated</dt><dd>15 Oct 2026 · 09:00 UTC</dd></div><div><dt>Scope</dt><dd>Account · sample contains one intervention</dd></div><div><dt>Source snapshot</dt><dd><code>93b0d1…8f27</code> · illustrative</dd></div><div><dt>Financial classification</dt><dd>Verification pending</dd></div></dl><div className="m-report-total"><span>Verified recovery</span><strong>{demo.verified}</strong></div><p className="m-report-disclosure">Post-action observation pending. Projection is an estimate. No causal result established.</p></div><div className="m-scene-foot">Frozen snapshot · PDF / CSV · Expiring, revocable sharing</div></ProductFrame>;
}

export function HeroScene() {
  return <div className="m-hero-scene"><div className="m-scene-index"><span>01 / FOLLOW THE EVIDENCE</span><span>ILLUSTRATIVE ACCOUNT</span></div><SearchScene/><div className="m-hero-decision"><span className="m-decision-connector" aria-hidden="true"/><div><span className="m-small-label">BUSINESS TRUTH · {demo.truthVersion}</span><strong>“We repair roofs.<br/>We don’t sell courses.”</strong><span className="m-hero-decision-foot">Northstar Roofing · Synthetic advertiser</span></div><span className="m-decision-check" aria-hidden="true">↳</span></div><div className="m-hero-caption"><span className="m-olive-dot"/> An observed problem. A reason. A controlled next step.</div></div>;
}
