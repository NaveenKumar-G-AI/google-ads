import Link from "next/link";
import type { Account,Membership,Portfolio,Workspace } from "@/lib/types";
import { ContextSwitcher } from "./context-switcher";
import { StatusBadge } from "./status-badge";

const groups=[
  ["Overview",[["Command Center","/app",true],["Accounts","/app/accounts",true],["Portfolios","/app/portfolios",true]]],
  ["Work",[["Tasks","/app/tasks",true],["Notifications","/app/notifications",true]]],
  ["Intelligence",[["Search Intelligence","/app/search-intelligence",true],["Waste Intelligence","/app/waste-intelligence",true],["Measurement","/app/measurement-integrity",true],["Budget & Bidding","",false],["Revenue Intelligence","",false]]],
  ["Operations",[["Action Center","/app/action-center",true],["Automation","",false],["Experiments","",false],["Monitoring & Alerts","/app/monitoring",true]]],
  ["Proof",[["Recovery Center","/app/recovery-center",true],["Reports","/app/reports",true]]],
  ["Organization",[["Business Truth","/app/business-truth",true],["Integrations","",false],["Team & Access","/app/organization",true],["Billing","/app/billing",true],["Security & Data","/app/security-data",true]]],
] as const;

export function AppShell({children,memberships,membership,accounts,portfolios,account,portfolio,workspace,unreadCount=0,email}:{children:React.ReactNode;memberships:Membership[];membership:Membership;accounts:Account[];portfolios:Portfolio[];account?:Account|null;portfolio?:Portfolio|null;workspace?:Workspace|null;unreadCount?:number;email?:string|null}){
  const base=new URLSearchParams({tenant:membership.tenant_id});if(account)base.set("account",account.id);if(portfolio)base.set("portfolio",portfolio.id);const qs=base.toString();
  const freshness=workspace?.latest_sync?.status||(!account?"organization":"unavailable");
  const restricted=(membership.account_access_mode??"all_accounts")!=="all_accounts";
  const canManageOrg=membership.role==="owner"||membership.role==="admin";
  return <div className="app-frame">
    <aside className="app-sidebar">
      <div className="product-mark"><span className="product-symbol">R</span><div><strong>Recovery OS</strong><small>Paid Search Revenue Recovery</small></div></div>
      <nav className="nav-groups">{groups.map(([group,items])=><section key={group}><div className="nav-group-title">{group}</div>{items.map(([name,href,enabled])=>{const blocked=(name==="Portfolios"&&restricted)||(name==="Team & Access"&&!canManageOrg);return enabled&&!blocked?<Link key={name} className="nav-item" href={`${href}?${qs}`}>{name}</Link>:<span key={name} className="nav-item nav-disabled" aria-disabled="true">{name}<em>{blocked?"restricted":"next epic"}</em></span>})}</section>)}</nav>
      <div className="sidebar-user"><span>{membership.role}</span><strong>{email||"Authenticated user"}</strong><Link href={`/app/profile?${qs}`}>Profile</Link></div>
    </aside>
    <div className="app-surface">
      <header className="app-topbar"><ContextSwitcher memberships={memberships} accounts={accounts} portfolios={portfolios} currentTenant={membership.tenant_id} currentAccount={account?.id} currentPortfolio={portfolio?.id}/><div className="top-actions">{account&&<Link className="freshness-chip" href={`/app/data-status?${qs}`}><StatusBadge value={freshness}/><span>Data</span></Link>}<Link className="icon-link" href={`/app/search?${qs}`} aria-label="Search">⌕</Link><Link className="icon-link notification-icon" href={`/app/notifications?${qs}`} aria-label={`${unreadCount} unread notifications`}>◉{unreadCount>0&&<b>{unreadCount>99?"99+":unreadCount}</b>}</Link><Link className="icon-link" href={`/app/help?${qs}`} aria-label="Help">?</Link></div></header>
      <main className="app-content">{children}</main>
    </div>
  </div>
}
