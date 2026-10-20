import type { Metadata } from "next";
import Link from "next/link";
import { getPublishedLegalDocument, supportMailto } from "@/lib/marketing-config";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Terms of Service | Recovery OS",
  description: "Access the current published Recovery OS Terms of Service when available.",
};

export default async function TermsPage() {
  const policy = await getPublishedLegalDocument("terms");
  const email = supportMailto("Request for current Recovery OS Terms of Service");
  return (
    <article className="m-utility">
      <p className="m-eyebrow">Legal</p>
      <h1>Terms of Service.</h1>
      {policy ? (
        <section className="m-card" aria-labelledby="terms-current">
          <h2 id="terms-current">Read the current published terms.</h2>
          <p>The linked document is the Terms of Service identified for workspace onboarding.</p>
          <p className="m-note">Version: {policy.version}</p>
          <a className="m-button" href={policy.url} rel="noreferrer">Read Terms of Service <span aria-hidden="true">↗</span></a>
        </section>
      ) : (
        <section className="m-card" aria-labelledby="terms-unavailable">
          <h2 id="terms-unavailable">The current terms are unavailable here.</h2>
          <p>Please request the published Terms of Service before creating a workspace. This page does not replace that document.</p>
          {email ? <a className="m-button" href={email}>Request the current terms <span aria-hidden="true">↗</span></a> : <Link className="m-button m-button-secondary" href="/recovery-review">View contact availability <span aria-hidden="true">↗</span></Link>}
        </section>
      )}
      <p><Link href="/privacy">Privacy Policy</Link> · <Link href="/security">Security &amp; control</Link></p>
    </article>
  );
}
