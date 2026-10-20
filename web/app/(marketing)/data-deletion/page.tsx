import type { Metadata } from "next";
import Link from "next/link";
import { getMarketingConfig, supportMailto } from "@/lib/marketing-config";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Data Requests & Deletion | Recovery OS",
  description: "How to request an organization data export, Google Ads disconnect or controlled organization deletion.",
};

export default function DataDeletionPage() {
  const { dataDeletionUrl } = getMarketingConfig();
  const email = supportMailto("Recovery OS data request");
  return (
    <article className="m-utility">
      <p className="m-eyebrow">Your data &amp; control</p>
      <h1>A clear path for<br />data requests.</h1>
      <p className="m-lead">Request a broader export, an advertiser disconnect or organization deletion from Security &amp; Data in your workspace.</p>
      <section className="m-card" aria-labelledby="data-request-steps">
        <h2 id="data-request-steps">Request organization deletion.</h2>
        <ol>
          <li>Sign in as the organization Owner.</li>
          <li>Open <strong>Security &amp; Data</strong> in the intended organization.</li>
          <li>Under <strong>Data operations</strong>, enter a reason in <strong>Delete organization</strong>.</li>
          <li>Select <strong>Request organization deletion</strong>.</li>
          <li>Review the request state in <strong>Data operations audit</strong>.</li>
        </ol>
        <Link prefetch={false} className="m-button" href="/app/security-data">Open Security &amp; Data <span aria-hidden="true">↗</span></Link>
        <p className="m-note">Submitting a request does not immediately erase the organization. Evidence remains until the controlled deletion workflow is completed.</p>
      </section>
      <section aria-labelledby="other-data-requests">
        <h2 id="other-data-requests">Export or disconnect an account.</h2>
        <p>Admins and Owners can download a bounded configuration and audit export, request a full organization export, or request a Google Ads advertiser disconnect from the same page.</p>
        <p>The direct export excludes provider credentials, refresh tokens, raw report-sharing tokens and billing secrets.</p>
      </section>
      {dataDeletionUrl && <p><a className="m-button m-button-secondary" href={dataDeletionUrl} rel="noreferrer">Read the published data-request guidance <span aria-hidden="true">↗</span></a></p>}
      <section aria-labelledby="data-access-help">
        <h2 id="data-access-help">Need help with a request?</h2>
        {email ? (
          <><p>Contact support with your organization name and the type of request. Do not include passwords or access tokens.</p><a className="m-button m-button-secondary" href={email}>Contact support <span aria-hidden="true">↗</span></a></>
        ) : <><p>Ask your organization Owner to submit the request. Signed-in members can also create a support case from Help &amp; Support.</p><Link prefetch={false} className="m-button m-button-secondary" href="/app/help">Open Help &amp; Support <span aria-hidden="true">↗</span></Link><p className="m-note">A public support email is not available here yet.</p></>}
      </section>
      <p><Link href="/privacy">Privacy Policy</Link> · <Link href="/security">Security &amp; control</Link></p>
    </article>
  );
}
