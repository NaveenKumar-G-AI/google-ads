/** Fictional illustration only. Keep every public product scene on this account. */
export const demo = {
  advertiser: "Northstar Roofing",
  campaign: "Austin · Residential Search",
  adGroup: "Roof repair",
  period: "1–30 Sep 2026",
  applied: "1 Oct 2026",
  projection: "2–31 Oct 2026",
  query: "free roofing course",
  protectedQuery: "roofing company",
  candidate: "$428",
  projected: "$428",
  observed: "Pending",
  verified: "$0",
  coverage: 78,
  truthVersion: "v3",
  fingerprint: "7ac93e…d41b",
} as const;

export const tourSteps = [
  { label: "Detect", title: "A search worth investigating.", body: "The visible search term “free roofing course” accumulated $428 in the September window. That is observed candidate exposure, not money recovered.", view: "search" },
  { label: "Inspect", title: "See the evidence before the verdict.", body: "The term came from Austin · Residential Search, in the Roof repair ad group. Visible terms cover 78% of Search spend. The remaining 22% is unknown, not inferred waste.", view: "search" },
  { label: "Diagnose", title: "A non-offer confirmed by the business.", body: "Northstar provides residential roof repair and replacement. Business Truth v3 explicitly excludes training. The primary enquiry mapping is confirmed; a page view marked primary still needs review. Downstream customer quality remains unknown.", view: "truth" },
  { label: "Propose", title: "One query. One precise proposed action.", body: "Propose an exact negative for “free roofing course” in Roof repair. Creating a proposal does not change Google Ads. Its approval is tied to the current Business Truth.", view: "action" },
  { label: "Check", title: "Protection can stop an unsafe decision.", body: "A separate proposal for “roofing company” collides with a protected commercial query and is blocked. The training query has no protected-query collision and can continue to review.", view: "collision" },
  { label: "Approve", title: "A person makes the consequential decision.", body: "An authorized owner or admin reviews and approves. A confirmed primary enquiry mapping and no measurement blockers permit this action, despite the page-view warning. This simulated approval writes nothing to Google Ads.", view: "action" },
  { label: "Apply", title: "A provider response needs a read-back.", body: "The simulated 1 October action passes provider validation and confirms the exact created negative by read-back. Its resource identity is retained for rollback. An uncertain effect would require reconciliation.", view: "applied" },
  { label: "Observe", title: "No observation yet is not zero spend.", body: "No post-action observation has been collected for this case. The initial ledger records the baseline and a projection; it does not establish subsequent query spend. Observation remains pending.", view: "recovery" },
  { label: "Classify", title: "Configuration verified. Financial proof pending.", body: "The latest analysis still shows $428 of candidate exposure. A separate $428 is historical acted-on exposure, and $428 is projected over 2–31 October. Observation is pending; verified recovery is $0. These classes are non-additive.", view: "recovery" },
] as const;
