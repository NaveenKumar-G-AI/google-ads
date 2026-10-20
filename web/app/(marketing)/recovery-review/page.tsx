import type { Metadata } from "next";
import Link from "next/link";
import { getMarketingConfig, supportMailto } from "@/lib/marketing-config";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Book a Recovery Review | Recovery OS",
  description: "Discuss your paid-search evidence, measurement concerns and account-control needs with Recovery OS.",
};

export default function RecoveryReviewPage() {
  const { reviewBookingUrl } = getMarketingConfig();
  const email = supportMailto("Recovery Review request");
  return (
    <article className="m-utility">
      <p className="m-eyebrow">A closer look</p>
      <h1>Start with the question<br />your report cannot answer.</h1>
      <p className="m-lead">Bring your measurement concerns, account footprint and the decisions you need to make. A Recovery Review starts there.</p>
      <section className="m-card" aria-labelledby="review-title">
        <h2 id="review-title">Your next step</h2>
        {reviewBookingUrl ? (
          <>
            <p>Choose a time using our booking page. Share the account context you are comfortable discussing.</p>
            <a className="m-button" href={reviewBookingUrl} rel="noreferrer">Book a Recovery Review <span aria-hidden="true">↗</span></a>
          </>
        ) : email ? (
          <>
            <p>Send a review request with your team size, approximate account count and the question you want to investigate.</p>
            <a className="m-button" href={email}>Request a Recovery Review <span aria-hidden="true">↗</span></a>
          </>
        ) : (
          <>
            <p>Recovery Review booking is not open on this site yet. Explore the product tour to see how evidence becomes a controlled decision.</p>
            <Link className="m-button" href="/demo">Explore the product tour <span aria-hidden="true">↗</span></Link>
          </>
        )}
        <p className="m-note">You do not need to connect Google Ads to explore the tour. It uses clearly labeled synthetic data.</p>
      </section>
      <section aria-labelledby="review-preparation">
        <h2 id="review-preparation">Three useful starting points.</h2>
        <ol>
          <li>The gap between reported conversions and the business outcomes you care about.</li>
          <li>The number of Google Search accounts your team operates.</li>
          <li>How you review changes and explain results to clients or leadership.</li>
        </ol>
        <p>Do not send passwords, access tokens or customer personal data.</p>
      </section>
      <p><Link prefetch={false} className="m-button m-button-secondary" href="/signup">Create an account <span aria-hidden="true">↗</span></Link></p>
      <p className="m-note">Workspace access follows the current launch availability. Google Ads authorization comes later in onboarding.</p>
    </article>
  );
}
