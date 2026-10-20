import type { Metadata } from "next";
import Link from "next/link";
import { getPublishedLegalDocument, supportMailto } from "@/lib/marketing-config";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Privacy Policy | Recovery OS",
  description: "Access the current published Recovery OS Privacy Policy and data-request guidance.",
};

export default async function PrivacyPage() {
  const policy = await getPublishedLegalDocument("privacy");
  const email = supportMailto("Request for current Recovery OS Privacy Policy");
  return (
    <article className="m-utility">
      <p className="m-eyebrow">Legal</p>
      <h1>Privacy Policy.</h1>
      {policy ? (
        <section className="m-card" aria-labelledby="privacy-current">
          <h2 id="privacy-current">Understand how your data is handled.</h2>
          <p>The linked document is the Privacy Policy identified for workspace onboarding.</p>
          <p className="m-note">Version: {policy.version}</p>
          <a className="m-button" href={policy.url} rel="noreferrer">Read Privacy Policy <span aria-hidden="true">↗</span></a>
        </section>
      ) : (
        <section className="m-card" aria-labelledby="privacy-unavailable">
          <h2 id="privacy-unavailable">The current policy is unavailable here.</h2>
          <p>Please request the published Privacy Policy before connecting an account. This page does not replace that document.</p>
          {email ? <a className="m-button" href={email}>Request the current policy <span aria-hidden="true">↗</span></a> : <Link className="m-button m-button-secondary" href="/recovery-review">View contact availability <span aria-hidden="true">↗</span></Link>}
        </section>
      )}
      <p><Link href="/data-deletion">Data requests &amp; deletion</Link> · <Link href="/security">Security &amp; control</Link></p>
    </article>
  );
}
