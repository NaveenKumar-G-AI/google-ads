import Link from "next/link";
import { AppShell } from "@/components/epic1/app-shell";
import { PageHeader } from "@/components/epic1/page-header";
import { EmptyState } from "@/components/epic1/empty-state";
import { StatusBadge } from "@/components/epic1/status-badge";
import { resolveAppContext } from "@/lib/epic1/context";
import { getSecurityDataOverview } from "@/lib/recovery-api";
import { dateTime,label } from "@/lib/format";
import { createDataRequestAction,cancelDataRequestAction } from "./actions";
export const dynamic="force-dynamic";

export default async function SecurityData({searchParams}:{searchParams:Promise<{tenant?:string;account?:string;portfolio?:string}>}){
  const q=await searchParams;
  const x=await resolveAppContext(q);
  if(!x.membership)return null;
  const d=await getSecurityDataOverview(x.membership.tenant_id);
  const canManage=["admin","owner"].includes(x.membership.role);
  const isOwner=x.membership.role==="owner";
  return <AppShell memberships={x.me.memberships} membership={x.membership} accounts={x.accounts} portfolios={x.portfolios} account={x.account} portfolio={x.portfolio} workspace={x.workspace} unreadCount={x.unreadCount} email={x.me.email}>
    <PageHeader eyebrow="Security & Data" title="Security and data controls" description="Access posture, connected-app permissions, retention boundaries, exports and controlled deletion/disconnect requests." actions={canManage?<Link className="secondary-action" href={`/api/security-data/export?tenant=${x.membership.tenant_id}`}>Download configuration & audit export</Link>:undefined}/>
    <div className="security-boundary"><strong>No direct destructive browser action.</strong><p>Organization deletion and Google Ads disconnect are controlled requests. OAuth secrets, raw share tokens and billing secrets are never included in customer exports.</p></div>
    <section className="summary-strip">
      <div><span>Your role</span><strong>{label(String(d.membership.role))}</strong></div>
      <div><span>Account access</span><strong>{label(String(d.membership.account_access_mode||"all_accounts"))}</strong></div>
      <div><span>Google connections</span><strong>{d.google_connections.filter(c=>c.status==="connected").length}</strong></div>
      <div><span>Data requests</span><strong>{d.data_requests.length}</strong></div>
      <div><span>Last seen</span><strong>{dateTime(d.membership.last_seen_at)}</strong></div>
    </section>
    <section className="section-stack">
      <div className="section-heading"><div><span className="section-kicker">Sessions & identity</span><h2>Current authenticated identity</h2></div></div>
      <div className="security-card-grid">
        <article><span>Email</span><strong>{String(d.membership.email||x.me.email||"—")}</strong><p>Recovery OS does not expose a hidden impersonation session in the customer product.</p></article>
        <article><span>Client portal</span><strong>{d.membership.client_portal?"Restricted client portal":"Standard workspace"}</strong><p>Account-level authorization is still enforced by the API even if a URL is typed manually.</p></article>
        <article><span>Legal acceptance</span><strong>{d.legal_acceptances[0]?`${d.legal_acceptances[0].terms_version} / ${d.legal_acceptances[0].privacy_version}`:"No acceptance visible"}</strong><p>{d.legal_acceptances[0]?`Accepted ${dateTime(d.legal_acceptances[0].accepted_at)}`:"Policy acceptance is stored per authenticated user."}</p></article>
      </div>
    </section>
    <section className="section-stack">
      <div className="section-heading"><div><span className="section-kicker">Integration permissions</span><h2>Google Ads authorization</h2></div></div>
      {d.google_connections.length?<div className="data-table-shell"><table className="data-table"><thead><tr><th>Status</th><th>Connected by</th><th>Scopes</th><th>Connected</th><th>Last verified</th></tr></thead><tbody>{d.google_connections.map((c:any)=><tr key={c.id}><td><StatusBadge value={c.status}/></td><td>{c.connected_by_email||String(c.connected_by).slice(0,8)}</td><td>{(c.granted_scopes||[]).map((s:string)=>s.split("/").pop()).join(", ")}</td><td>{dateTime(c.connected_at)}</td><td>{dateTime(c.last_verified_at)}</td></tr>)}</tbody></table></div>:<EmptyState title="No Google OAuth connection" body="Google Ads authorization will appear here after onboarding."/>}
    </section>
    <section className="section-stack">
      <div className="section-heading"><div><span className="section-kicker">Retention</span><h2>What Recovery OS retains</h2></div></div>
      <div className="retention-grid">{Object.entries(d.retention).map(([k,v])=><article key={k}><strong>{label(k)}</strong><p>{v}</p></article>)}</div>
    </section>
    {canManage&&<section className="section-stack">
      <div className="section-heading"><div><span className="section-kicker">Controlled requests</span><h2>Data operations</h2></div></div>
      <div className="data-request-forms">
        <form action={createDataRequestAction}><input type="hidden" name="tenant" value={x.membership.tenant_id}/><input type="hidden" name="request_type" value="full_data_export"/><strong>Full organization data export</strong><p>The direct download above is a bounded configuration/audit export. Use this request for a broader controlled export.</p><textarea name="reason" required placeholder="Why is the full export needed?"/><button className="secondary-action">Request full export</button></form>
        <form action={createDataRequestAction}><input type="hidden" name="tenant" value={x.membership.tenant_id}/><input type="hidden" name="request_type" value="google_ads_disconnect"/><strong>Disconnect an advertiser account</strong><select name="account_id" required defaultValue={x.account?.id||""}><option value="" disabled>Select account</option>{x.accounts.map(a=><option key={a.id} value={a.id}>{a.descriptive_name||a.customer_id}</option>)}</select><textarea name="reason" required placeholder="Why should provider access be disconnected?"/><button className="secondary-action">Request disconnect</button></form>
        {isOwner&&<form action={createDataRequestAction} className="danger-request"><input type="hidden" name="tenant" value={x.membership.tenant_id}/><input type="hidden" name="request_type" value="organization_deletion"/><strong>Delete organization</strong><p>This creates a controlled deletion request. It does not erase evidence immediately from the browser.</p><textarea name="reason" required placeholder="Reason for organization deletion"/><button className="secondary-action danger-text">Request organization deletion</button></form>}
      </div>
    </section>}
    <section className="section-stack">
      <div className="section-heading"><div><span className="section-kicker">Request history</span><h2>Data operations audit</h2></div></div>
      {d.data_requests.length?<div className="data-table-shell"><table className="data-table"><thead><tr><th>Request</th><th>State</th><th>Created</th><th>Reason</th>{canManage&&<th/>}</tr></thead><tbody>{d.data_requests.map(r=><tr key={r.id}><td>{label(r.request_type)}</td><td><StatusBadge value={r.state}/></td><td>{dateTime(r.created_at)}</td><td>{r.reason}</td>{canManage&&<td>{!["cancelled","completed","rejected"].includes(r.state)&&<form action={cancelDataRequestAction}><input type="hidden" name="tenant" value={x.membership!.tenant_id}/><input type="hidden" name="request_id" value={r.id}/><button className="link-button">Cancel request</button></form>}</td>}</tr>)}</tbody></table></div>:<EmptyState title="No data requests" body="Controlled export, disconnect and deletion requests will remain visible here."/>}
    </section>
    <section className="section-stack">
      <div className="section-heading"><div><span className="section-kicker">Security activity</span><h2>Recent access/security-related events</h2></div></div>
      {d.security_events.length?<div className="timeline-list">{d.security_events.map((e:any)=><article key={e.id}><div><strong>{label(e.event_type)}</strong><span>{dateTime(e.occurred_at)}</span></div><small>{e.target_type} · {e.target_id||"organization"}</small></article>)}</div>:<EmptyState title="No matching security activity" body="Membership, access, invite and data-operation events will appear here."/>}
    </section>
  </AppShell>
}
