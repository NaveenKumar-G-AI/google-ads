import type { Metadata } from "next";
import Link from "next/link";
import { getMarketingConfig } from "@/lib/marketing-config";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Service Status | Recovery OS",
  description: "Find the published Recovery OS service-status page and account-level monitoring.",
};

export default function StatusPage() {
  const { statusUrl } = getMarketingConfig();
  return (
    <article className="m-utility">
      <p className="m-eyebrow">Service information</p>
      <h1>Service status.</h1>
      <section className="m-card" aria-labelledby="status-availability">
        <h2 id="status-availability">{statusUrl ? "Check the published service updates." : "A public status page is not available yet."}</h2>
        {statusUrl ? (
          <>
            <p>Open the service-status page for published incident updates and service information.</p>
            <a className="m-button" href={statusUrl} rel="noreferrer">Open service status <span aria-hidden="true">↗</span></a>
          </>
        ) : <p>This page does not report live service health or an uptime figure.</p>}
      </section>
      <section aria-labelledby="account-monitoring">
        <h2 id="account-monitoring">Looking for your account&apos;s data health?</h2>
        <p>Inside your workspace, Monitoring shows data freshness, measurement issues, campaign-serving signals and actions that need reconciliation.</p>
        <Link prefetch={false} className="m-button m-button-secondary" href="/app/monitoring">Open account monitoring <span aria-hidden="true">↗</span></Link>
        <p className="m-note">Sign-in is required. Account monitoring is separate from service availability.</p>
      </section>
    </article>
  );
}
