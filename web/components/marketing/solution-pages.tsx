import { MarketingLink, ProductTour } from "./interactive";
import { FinalCTA, PageHero, ProcessStrip, SectionHeading } from "./primitives";
import { ActionScene, MeasurementScene, MonitoringScene, RecoveryScene, ReportScene, SearchScene, TruthScene } from "./scenes";

function ReviewLink({ source }: { source: "for_agencies" | "for_brands" | "pricing" | "security" | "reporting" }) {
  return <MarketingLink href="/recovery-review" className="m-button m-button-secondary" event="book_review_click" source={source}>Book a Recovery Review <span aria-hidden="true">↗</span></MarketingLink>;
}

function FAQ({ items }: { items: { question: string; answer: string }[] }) {
  return <div className="m-faq">{items.map(({ question, answer }) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div>;
}

export function ProductPage() {
  return <>
    <PageHero source="product" eyebrow="THE RECOVERY OPERATING MODEL" title={<>A clear line from evidence<br/><em>to accountable action.</em></>} description="Understand the searches you paid for, test them against the business you run, and keep every decision attached to its evidence." />
    <section className="m-container m-section"><h2 className="m-sr-only">The five-stage recovery workflow</h2><ProcessStrip/><nav className="m-inline-checks" aria-label="Explore the product"><a href="#search-evidence">Search evidence</a><a href="#measurement">Measurement</a><a href="#business-truth">Business Truth</a><a href="#monitoring">Monitoring</a></nav></section>

    <section id="search-evidence" className="m-container m-section m-split">
      <div><SectionHeading number="01" eyebrow="SEARCH EVIDENCE" title={<>Inspect the query.<br/>Keep the context.</>}>Look at visible search terms and recurring phrases with campaign, ad group, match and network context.</SectionHeading>
        <ul className="m-editorial-list"><li>Review the exact analysis window and observed spend.</li><li>Understand the business reason a query needs attention.</li><li>Keep hidden Search traffic outside the waste claim.</li></ul>
        <p className="m-note">In this synthetic account, 78% of Search spend is visible. The remaining 22% is unknown, not presumed waste.</p>
      </div><SearchScene/>
    </section>

    <section id="measurement" className="m-dark-section"><div className="m-container m-section m-split"><MeasurementScene/><div>
      <SectionHeading number="02" eyebrow="MEASUREMENT INTEGRITY" title={<>Before you trust the result,<br/><em>check what was counted.</em></>}>Map conversion actions to real business outcomes, supporting signals or non-outcomes, then inspect goals and observed lag.</SectionHeading>
      <ul className="m-editorial-list"><li><strong>Strong:</strong> the assessed measurement requirements are met.</li><li><strong>Constrained:</strong> limitations narrow the claims you can make.</li><li><strong>Blocked:</strong> conversion-dependent decisions cannot proceed.</li><li><strong>Unknown:</strong> there is not enough evidence for confidence.</li></ul>
      <p className="m-note">A recorded enquiry does not independently prove a qualified lead, customer or sale.</p>
    </div></div></section>

    <section id="business-truth" className="m-container m-section m-split"><div>
      <SectionHeading number="03" eyebrow="BUSINESS TRUTH" title={<>Make business fit<br/><em>an explicit decision.</em></>}>Publish the offers, non-offers, audiences, service areas and protected queries that explain what belongs in the account.</SectionHeading>
      <p className="m-pullquote">“We repair roofs. We don’t sell courses.”</p>
      <p>For Northstar Roofing, that distinction is the reason to review a training query. It is more useful than a weak metric on its own.</p>
      <p className="m-note">Each published version has a fingerprint. Approval checks the current version before a change can proceed.</p>
    </div><TruthScene/></section>

    <section className="m-container m-section m-split"><ActionScene blocked/><div>
      <SectionHeading number="04" eyebrow="ACTION CENTER" title={<>A precise change.<br/>A deliberate approval.</>}>Review an exact ad-group negative proposal, including its evidence and protected-query checks, before an authorized person approves it.</SectionHeading>
      <ul className="m-editorial-list"><li>Provider validation precedes application.</li><li>Read-back checks the exact created resource.</li><li>An uncertain provider effect goes to reconciliation.</li><li>Rollback targets the recorded resource identity.</li></ul>
      <p className="m-note">Current execution is limited to exact ad-group negative keywords. Budgets, bids and campaigns are not automatically changed.</p>
      <a href="/security" className="m-text-link">Understand approval and control →</a>
    </div></section>

    <section className="m-container m-section m-split"><div>
      <SectionHeading number="05" eyebrow="RECOVERY CENTER" title={<>Watch what follows.<br/><em>Name what you know.</em></>}>Separate candidate exposure, historical action, projected prevention, observed spend and verified recovery.</SectionHeading>
      <p className="m-large-statement">A successful account change is not proof of savings.</p>
      <p>These financial classes answer different questions. They are never added together to create a recovery total.</p>
      <p className="m-note">In this example, the configuration is verified. No post-action observation has been collected. Financial verification remains pending, with $0 verified recovery.</p>
    </div><RecoveryScene/></section>

    <section id="monitoring" className="m-container m-section m-split"><MonitoringScene/><div>
      <SectionHeading number="06" eyebrow="MONITORING & ATTENTION" title={<>Keep the next review<br/>within reach.</>}>Bring freshness, measurement, job status, serving status and reconciliation into an account’s attention queue.</SectionHeading>
      <p>Checks run after sync or when requested. Statistical anomaly monitors are optional, so the team can choose where they belong.</p>
      <p className="m-note">Monitoring reflects the latest available evidence. It is not a promise of continuous, real-time surveillance.</p>
      <a href="/reporting" className="m-text-link">Take the evidence into a report →</a>
    </div></section>
    <FinalCTA/>
  </>;
}

export function AgenciesPage() {
  return <>
    <PageHero source="for_agencies" eyebrow="RECOVERY OS FOR AGENCIES" title={<>Know which client<br/><em>needs you next.</em></>} description="Prioritize account attention, keep decision context with the work, and bring evidence into the client conversation." />
    <section className="m-container m-section m-split"><div>
      <SectionHeading eyebrow="PRIORITIZATION" title={<>Start the day with a reason<br/>to open the account.</>}>Review stale evidence, measurement constraints, pending decisions and uncertain provider effects across the accounts your role can access.</SectionHeading>
      <ul className="m-editorial-list"><li>Which account needs attention today?</li><li>Which measurement issue changes the story?</li><li>Which proposed action is still waiting for a decision?</li></ul>
      <p className="m-note">Monitoring is evaluated after sync or on request. Account access determines what each teammate can see.</p>
    </div><MonitoringScene/></section>

    <section className="m-dark-section"><div className="m-container m-section m-split"><TruthScene/><div>
      <SectionHeading eyebrow="CONTEXT THAT STAYS WITH THE CLIENT" title={<>A new strategist shouldn’t<br/><em>start from zero.</em></>}>Keep the client’s offers, exclusions, service areas and protected commercial intent in a versioned Business Truth profile.</SectionHeading>
      <p>Northstar Roofing is a fictional example, but the handover question is familiar: why is a training query wrong for this client, and why must “roofing company” stay protected?</p>
      <p className="m-pullquote">The reason should survive the handover.</p>
    </div></div></section>

    <section className="m-container m-section"><SectionHeading eyebrow="CONTROL" title={<>Shared work.<br/><em>Clear authority.</em></>}>Give teammates the visibility they need, and keep account changes behind the appropriate approval.</SectionHeading>
      <div className="m-grid-three"><article className="m-card"><span className="m-eyebrow">01 / TEAM</span><h3>Separate review from execution.</h3><p>Analysts investigate and prepare work. Owners and Admins hold approval and execution authority.</p></article><article className="m-card"><span className="m-eyebrow">02 / CLIENT</span><h3>Limit the view to the client.</h3><p>Client-facing membership uses Viewer access to selected accounts. Other clients remain outside that access boundary.</p></article><article className="m-card"><span className="m-eyebrow">03 / ACCOUNT</span><h3>Keep responsibility explicit.</h3><p>Account responsibility assignments help organize work. They do not silently grant account access.</p></article></div>
    </section>

    <section className="m-container m-section m-split"><div>
      <SectionHeading eyebrow="PROOF" title={<>Bring a defensible story<br/>to the monthly call.</>}>Generate an evidence snapshot that separates what was observed, what changed and what remains unverified.</SectionHeading>
      <p>Monthly Client and Agency Portfolio reports preserve the source context at generation. PDF and CSV exports give the conversation a stable reference.</p>
      <p className="m-note">Report scope and disclosures stay visible. Organization monitoring context can include accounts outside a selected portfolio.</p>
      <a href="/reporting" className="m-text-link">Explore evidence reporting →</a>
    </div><ReportScene/></section>

    <section className="m-container m-section"><SectionHeading eyebrow="BEGIN WITH A CLIENT YOU KNOW" title={<>A focused pilot.<br/>A better operating conversation.</>}>Choose an eligible advertiser, agree the business definitions, and review the evidence before considering a controlled change.</SectionHeading><ReviewLink source="for_agencies"/></section>
    <FinalCTA/>
  </>;
}

export function BrandsPage() {
  return <>
    <PageHero source="for_brands" eyebrow="FOR BRANDS & IN-HOUSE TEAMS" title={<>Know what stands<br/><em>behind performance.</em></>} description="Bring marketing, leadership and agency partners around the same business definitions, measurement limits and account evidence." />
    <section className="m-container m-section"><SectionHeading eyebrow="ONE CONVERSATION, DIFFERENT SIGNALS" title={<>Conversions went up.<br/>The questions didn’t go away.</>}>When marketing reports growth and sales questions quality, start by checking what the account is actually counting.</SectionHeading>
      <div className="m-grid-three"><article className="m-card"><span className="m-eyebrow">MARKETING</span><h3>What did the account record?</h3><p>Inspect conversion actions and their relationship to your stated business outcomes.</p></article><article className="m-card"><span className="m-eyebrow">BUSINESS</span><h3>What is a good enquiry?</h3><p>Document the offers, audience and service area that give a search commercial meaning.</p></article><article className="m-card"><span className="m-eyebrow">LEADERSHIP</span><h3>What can we substantiate?</h3><p>Keep observed evidence separate from estimates, assumptions and financial verification.</p></article></div>
    </section>

    <section className="m-container m-section m-split"><TruthScene/><div>
      <SectionHeading eyebrow="BUSINESS TRUTH" title={<>Your definition of good<br/><em>belongs in the workflow.</em></>}>Make the team’s business knowledge part of query review instead of leaving it in an onboarding call or a slide deck.</SectionHeading>
      <p>Northstar Roofing sells roof repair and replacement in Austin. Training is a non-offer. Searches for roofing services need a different judgement from job or course searches.</p>
      <p className="m-note">Business Truth provides decision context. It does not replace CRM records or independently measure downstream revenue.</p>
    </div></section>

    <section className="m-dark-section"><div className="m-container m-section m-split"><div>
      <SectionHeading eyebrow="MEASUREMENT CONFIDENCE" title={<>Name the uncertainty.<br/><em>Then make the decision.</em></>}>Use strong, constrained, blocked and unknown states to show which conversion-dependent conclusions the evidence supports.</SectionHeading>
      <div className="m-equations"><span>Recorded lead <b>≠</b> qualified lead</span><span>Approved change <b>≠</b> verified recovery</span></div>
      <p>Outcome mappings, account goals and observed lag help qualify the interpretation. A missing downstream signal stays missing.</p>
    </div><MeasurementScene/></div></section>

    <section className="m-container m-section m-split"><ActionScene/><div>
      <SectionHeading eyebrow="ACCOUNTABLE CHANGE" title={<>Keep control of<br/>what happens next.</>}>Review the reason, the precise target and the protected-query checks before an authorized approval.</SectionHeading>
      <p>V1 applies exact ad-group negative keywords through provider validation and read-back. An uncertain effect is held for reconciliation instead of silently retried.</p>
      <a href="/security" className="m-text-link">See the control model →</a>
    </div></section>

    <section className="m-container m-section m-split"><div>
      <SectionHeading eyebrow="LEADERSHIP REPORTING" title={<>A result you can discuss.<br/><em>A limit you can see.</em></>}>Share a frozen snapshot of the evidence and its financial classification, with the report’s scope and disclosures attached.</SectionHeading>
      <p>The Northstar example shows a verified configuration change and $0 verified recovery. That distinction belongs in the conversation.</p>
      <ReviewLink source="for_brands"/>
    </div><ReportScene/></section>
    <FinalCTA/>
  </>;
}

const reportFamilies = [
  ["Executive Recovery", "A view of the separate financial evidence classes."],
  ["Waste Intelligence", "Observed candidates, analysis context and coverage limits."],
  ["Measurement Integrity", "Conversion mappings, goals and observed lag."],
  ["Search Demand", "Visible search evidence and its analysis window."],
  ["Account Health", "Account evidence and measurement context."],
  ["Change Impact", "Recorded interventions and their available ledger evidence."],
  ["Monthly Client", "A client account’s evidence for a reporting conversation."],
  ["Agency Portfolio", "Portfolio recovery evidence with scope disclosures."],
] as const;

export function ReportingPage() {
  return <>
    <PageHero source="reporting" eyebrow="EVIDENCE REPORTING" title={<>Send proof.<br/><em>Keep its context.</em></>} description="Turn product evidence into a frozen report, with its generation time, scope and relevant disclosures preserved." />
    <section className="m-container m-section m-split"><div>
      <SectionHeading eyebrow="A STABLE REFERENCE" title={<>Yesterday’s report doesn’t change<br/>because today’s account did.</>}>Each generation captures the source state. PDF and CSV artifacts preserve that snapshot rather than recalculating the live account.</SectionHeading>
      <ul className="m-editorial-list"><li>Generation time and account or portfolio scope.</li><li>Source snapshot and artifact hashes.</li><li>Financial classification and non-additive disclosure.</li><li>Report-specific measurement, mappings and evidence context.</li></ul>
      <p className="m-note">Available evidence fields depend on the report type and source data. The scene shown is a synthetic illustration, not a customer report.</p>
    </div><ReportScene/></section>

    <section className="m-dark-section"><div className="m-container m-section m-split"><RecoveryScene/><div>
      <SectionHeading eyebrow="FINANCIAL TRUTH TRAVELS WITH THE REPORT" title={<>An estimate stays an estimate.<br/><em>Even in the PDF.</em></>}>The same financial boundaries apply in a client report as in the product.</SectionHeading>
      <p>Current candidate exposure, historical acted-on exposure, projected prevention, observed post-action spend and verified recovery remain separate.</p>
      <p className="m-large-statement">No synthetic savings total.</p>
      <p className="m-note">Unobserved Search spend remains a coverage limitation. It does not become waste or recovery through reporting.</p>
    </div></div></section>

    <section className="m-container m-section"><SectionHeading eyebrow="EIGHT REPORT PRESETS" title={<>Choose the question.<br/><em>Carry the evidence.</em></>}>Use a focused report family for the conversation you need to have.</SectionHeading>
      <div className="m-grid-two">{reportFamilies.map(([title, description], index) => <article className="m-card" key={title}><span className="m-eyebrow">{String(index + 1).padStart(2, "0")} / REPORT PRESET</span><h3>{title}</h3><p>{description}</p></article>)}</div>
      <p className="m-note">Current reports use fixed presets. An arbitrary report builder and advanced white-label designer are not included in V1.</p>
      <p className="m-note">Agency Portfolio reports include organization monitoring context, which can contain accounts outside the selected portfolio. Monthly Client recovery evidence is current or cumulative as of generation, not limited to that month.</p>
    </section>

    <section className="m-container m-section"><SectionHeading eyebrow="SHARING WITH BOUNDARIES" title={<>A report can leave the workspace.<br/>Its access should still have limits.</>}>Create expiring links, revoke them when needed, or download a PDF or CSV artifact.</SectionHeading>
      <div className="m-grid-three"><article className="m-card"><h3>Time-limited access.</h3><p>Shared links have a required expiry. Only a hash of the secret sharing token is stored.</p></article><article className="m-card"><h3>Revocable sharing.</h3><p>Authorized teammates can revoke a link. Anyone who holds an active link can view its report, so share it deliberately.</p></article><article className="m-card"><h3>Repeatable reporting.</h3><p>Schedules use explicit timezones and complete reporting periods. Email delivery is optional when configured.</p></article></div>
      <p className="m-note">Revoking a link cannot recall an artifact someone has already downloaded.</p>
      <ReviewLink source="reporting"/>
    </section>
    <FinalCTA/>
  </>;
}

export function SecurityPage() {
  return <>
    <PageHero source="security" eyebrow="SECURITY & CONTROL" title={<>Control first.<br/><em>Automation second.</em></>} description="Understand what Recovery OS can access, who can approve changes, and how uncertain outcomes are handled." />
    <section className="m-container m-section m-split"><div>
      <SectionHeading eyebrow="GOOGLE AUTHORIZATION" title={<>Start by observing.<br/>Change only with approval.</>}>Your first sync reads account evidence. A proposal by itself never changes Google Ads.</SectionHeading>
      <p>Google’s authorization grant supports account management; it is not a read-only OAuth permission. Recovery OS applies its own role, approval and execution checks before a supported change.</p>
      <p className="m-note">Current execution supports exact ad-group negative keywords. There are no automatic budget, bid or campaign changes.</p>
    </div><ActionScene/></section>

    <section className="m-container m-section"><SectionHeading eyebrow="WHO CAN DO WHAT" title={<>The person reviewing evidence<br/>needn’t hold the keys.</>}>Organization roles and account authorization are enforced by the backend, with tenant isolation in the data layer.</SectionHeading>
      <div className="m-grid-three"><article className="m-card"><span className="m-eyebrow">OWNER / ADMIN</span><h3>Accountable authority.</h3><p>Owners and Admins can approve and execute supported account changes, subject to current evidence and safety gates.</p></article><article className="m-card"><span className="m-eyebrow">ANALYST</span><h3>Evidence and preparation.</h3><p>Analysts can investigate and prepare work. They cannot approve or execute Google Ads mutations.</p></article><article className="m-card"><span className="m-eyebrow">VIEWER / CLIENT</span><h3>Visibility with boundaries.</h3><p>Viewer access is for reading. Client-facing membership is limited to selected accounts.</p></article></div>
      <p className="m-note">Recovery OS membership does not grant access inside Google Ads itself.</p>
    </section>

    <section className="m-dark-section"><div className="m-container m-section m-split"><ActionScene blocked/><div>
      <SectionHeading eyebrow="BEFORE AND AFTER A CHANGE" title={<>Approval starts the checks.<br/><em>It doesn’t bypass them.</em></>}>Current Business Truth, protected-query collisions and provider validation remain part of execution.</SectionHeading>
      <ul className="m-editorial-list"><li>Recheck the evidence and current truth before applying.</li><li>Validate with the provider before mutation.</li><li>Read back the exact created resource.</li><li>Hold ambiguous effects for reconciliation.</li><li>Use the recorded resource identity for rollback and verify its absence.</li></ul>
      <p className="m-note">Operational mutation gates can prevent execution. An uncertain provider response is not automatically replayed.</p>
    </div></div></section>

    <section className="m-container m-section"><SectionHeading eyebrow="DATA & SHARING" title={<>Useful access.<br/><em>Deliberate limits.</em></>}>Keep secrets out of exports and retain a controlled path for broader data operations.</SectionHeading>
      <div className="m-grid-two"><article className="m-card"><h3>Bounded configuration export.</h3><p>Authorized administrators can export safe configuration and audit metadata. Provider credentials, refresh tokens, raw sharing tokens and billing secrets are excluded.</p></article><article className="m-card"><h3>Controlled data requests.</h3><p>Request a fuller organization export, an advertiser disconnect or organization deletion through Security &amp; Data. A request is not an immediate destructive operation.</p><a href="/data-deletion" className="m-text-link">See the data-request process →</a></article><article className="m-card"><h3>Report access can expire.</h3><p>Capability links have mandatory expiry and can be revoked. Stored token hashes avoid retaining the raw sharing secret.</p><a href="/reporting" className="m-text-link">Understand report sharing →</a></article><article className="m-card"><h3>Access has a record.</h3><p>Membership, invitation and other administrative events retain audit context. Account responsibility and account visibility remain separate.</p></article></div>
    </section>

    <section className="m-container m-section"><SectionHeading eyebrow="QUESTIONS WORTH ASKING" title={<>Clear answers<br/>before you connect.</>}/><FAQ items={[
      { question: "Does connecting Google Ads immediately change my account?", answer: "No. The first sync reads account data. Supported changes need an authorized approval, current evidence and execution checks. Google’s OAuth grant itself does allow account management." },
      { question: "Can a protected query still be proposed as a negative?", answer: "A proposal can be inspected, but a protected commercial-query collision blocks the action. Weak metrics alone do not override that protection." },
      { question: "Does a verified change mean verified savings?", answer: "No. Read-back can verify the configuration. Financial recovery requires separate causal evidence and remains unverified when that evidence is missing." },
      { question: "Is enterprise SSO or a security certification included?", answer: "Enterprise SSO is not part of V1. No security certification is claimed here. Discuss your procurement requirements before agreeing access or commercial terms." },
    ]}/><ReviewLink source="security"/></section>
    <FinalCTA/>
  </>;
}

const accessTracks = [
  { name: "Starter", audience: "A focused in-house team.", description: "Discuss a limited advertiser footprint and one clear evidence workflow.", scope: "Account fit · business definitions · initial review" },
  { name: "Growth", audience: "A team with more accounts.", description: "Discuss how your advertisers, responsibilities and reporting needs fit together.", scope: "Account scope · team roles · reporting cadence" },
  { name: "Agency", audience: "Client work, with context.", description: "Discuss client boundaries, collaborative review and evidence-led reporting.", scope: "Client access · account responsibility · portfolio review" },
  { name: "Enterprise", audience: "A considered evaluation.", description: "Discuss governance, procurement and scale requirements against the current product.", scope: "Requirement review · data controls · pilot boundaries" },
] as const;

export function PricingPage() {
  return <>
    <PageHero source="pricing" eyebrow="PRICING & EARLY ACCESS" title={<>Start with the right scope.<br/><em>Agree the terms together.</em></>} description="Discuss your accounts, team and evidence needs. Pilot eligibility, access and commercial terms are confirmed before activation." />
    <section className="m-container m-section"><SectionHeading eyebrow="FOUR WAYS TO START THE CONVERSATION" title={<>Choose the context<br/>that sounds like yours.</>}>These are discussion tracks, not fixed packages or a promise of feature availability.</SectionHeading>
      <div className="m-grid-two">{accessTracks.map(track => <article className="m-card" key={track.name}><span className="m-eyebrow">EARLY ACCESS / DISCUSS SCOPE</span><h3>{track.name}</h3><p className="m-lead">{track.audience}</p><p>{track.description}</p><p className="m-note">{track.scope}</p><MarketingLink className="m-text-link" href="/recovery-review" event="book_review_click" source="pricing">Discuss {track.name.toLowerCase()} access <span aria-hidden="true">↗</span></MarketingLink></article>)}</div>
      <p className="m-note">Pricing is not publicly fixed. No free trial, guaranteed activation, account allowance or contractual service level is implied by these tracks.</p>
    </section>

    <section className="m-dark-section"><div className="m-container m-section"><SectionHeading eyebrow="A USEFUL FIRST REVIEW" title={<>Before a commercial commitment,<br/><em>get specific.</em></>}>A scoped evaluation should establish the account, the business definition and the evidence you intend to review.</SectionHeading>
      <div className="m-grid-three"><article className="m-card"><span className="m-eyebrow">01 / FIT</span><h3>Your account and team.</h3><p>Confirm the Google Ads advertiser scope, responsible people and access needs.</p></article><article className="m-card"><span className="m-eyebrow">02 / EVIDENCE</span><h3>Your decision criteria.</h3><p>Define offers, exclusions and outcomes. Review measurement constraints before interpreting performance.</p></article><article className="m-card"><span className="m-eyebrow">03 / TERMS</span><h3>Your agreed next step.</h3><p>Confirm pilot eligibility, commercial terms and operational limits before activation.</p></article></div>
      <ReviewLink source="pricing"/>
    </div></section>

    <section className="m-container m-section"><SectionHeading eyebrow="ACCESS QUESTIONS" title={<>Know what the first<br/>step actually means.</>}/><FAQ items={[
      { question: "Can I explore the product before connecting an account?", answer: "Yes. The interactive product tour uses Northstar Roofing, a fictional advertiser. No Google account is connected and no real change is made." },
      { question: "Does creating an account guarantee pilot access?", answer: "No. Workspace creation and activation depend on launch eligibility and applicable legal and commercial requirements. Signup and Google Ads authorization are separate steps." },
      { question: "Are different features promised by these four tracks?", answer: "No. The tracks identify the kind of conversation to have. Scope, availability and commercial terms must be confirmed for your workspace." },
      { question: "Does Enterprise include SSO or custom integrations?", answer: "No such entitlement is implied. Enterprise SSO, deep CRM integrations and cross-channel support are outside the current V1 scope." },
    ]}/><a className="m-text-link" href="/demo">Explore the product tour →</a></section>
    <FinalCTA/>
  </>;
}

export function DemoPage() {
  return <>
    <PageHero source="product_tour" eyebrow="INTERACTIVE PRODUCT TOUR" title={<>One search.<br/><em>The whole decision.</em></>} description="Follow Northstar Roofing from an observed training query to a controlled negative-keyword action, then see what the financial evidence can and cannot prove." />
    <section className="m-container m-section" aria-label="Interactive synthetic advertiser walkthrough"><ProductTour/></section>
    <section className="m-container m-section"><SectionHeading eyebrow="THE DEMO’S GROUND RULES" title={<>A fictional account.<br/><em>Real product boundaries.</em></>}>The walkthrough illustrates the implemented workflow with synthetic data. It is not a customer result or a live Google Ads account.</SectionHeading>
      <div className="m-grid-three"><article className="m-card"><h3>One business definition.</h3><p>Northstar Roofing provides residential roof repair and replacement in Austin. It does not sell training, jobs or DIY materials.</p></article><article className="m-card"><h3>One supported action.</h3><p>The proposed change is an exact ad-group negative for “free roofing course.” A collision with protected “roofing company” is blocked.</p></article><article className="m-card"><h3>No invented recovery.</h3><p>All amounts are illustrative. A verified configuration still leaves $0 verified recovery while causal evidence is missing.</p></article></div>
      <p className="m-note">The baseline covers 1–30 September 2026. The simulated action is applied on 1 October, followed by a 30-day run-rate projection for 2–31 October. No post-action observation is collected in this example. The latest analysis still shows $428 of candidate exposure until it is refreshed. Financial classes are non-additive.</p>
    </section>
    <FinalCTA/>
  </>;
}
