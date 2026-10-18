"use client";
import { useRouter } from "next/navigation";
import type { Account, Membership, Portfolio } from "@/lib/types";

export function ContextSwitcher({memberships,accounts,portfolios,currentTenant,currentAccount,currentPortfolio}:{memberships:Membership[];accounts:Account[];portfolios:Portfolio[];currentTenant:string;currentAccount?:string|null;currentPortfolio?:string|null}){
  const router=useRouter();
  const org=(tenant:string)=>router.push(`/app?tenant=${encodeURIComponent(tenant)}`);
  const portfolio=(id:string)=>id?router.push(`/app/portfolios/${encodeURIComponent(id)}?tenant=${encodeURIComponent(currentTenant)}&portfolio=${encodeURIComponent(id)}`):router.push(`/app?tenant=${encodeURIComponent(currentTenant)}`);
  const account=(id:string)=>id?router.push(`/app/accounts/${encodeURIComponent(id)}?tenant=${encodeURIComponent(currentTenant)}&account=${encodeURIComponent(id)}`):router.push(`/app?tenant=${encodeURIComponent(currentTenant)}`);
  return <div className="context-switcher" aria-label="Operating context">
    <label><span>Organization</span><select value={currentTenant} onChange={e=>org(e.target.value)}>{memberships.map(m=><option key={m.tenant_id} value={m.tenant_id}>{m.tenant_name||m.tenant_id.slice(0,8)}</option>)}</select></label>
    <label><span>Portfolio</span><select value={currentPortfolio||""} onChange={e=>portfolio(e.target.value)}><option value="">All accounts</option>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <label><span>Account</span><select value={currentAccount||""} onChange={e=>account(e.target.value)}><option value="">Organization scope</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.descriptive_name||a.customer_id}</option>)}</select></label>
  </div>
}
