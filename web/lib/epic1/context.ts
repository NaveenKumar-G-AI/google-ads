import { redirect } from "next/navigation";
import { getAccounts, getMe, getNotifications, getPortfolios, getWorkspace } from "@/lib/recovery-api";

export async function resolveAppContext(params:{tenant?:string;account?:string;portfolio?:string}){
  const me=await getMe();
  const membership=params.tenant?me.memberships.find(m=>m.tenant_id===params.tenant):me.memberships[0];
  if(!membership) return {me,membership:null,accounts:[],portfolios:[],account:null,portfolio:null,workspace:null,unreadCount:0};
  const unrestricted=(membership.account_access_mode??"all_accounts")==="all_accounts";
  const [accounts,portfolios,unread]=await Promise.all([
    getAccounts(membership.tenant_id),
    unrestricted?getPortfolios(membership.tenant_id):Promise.resolve([]),
    getNotifications(membership.tenant_id,true),
  ]);
  const account=params.account?accounts.find(a=>a.id===params.account)??null:null;
  const portfolio=params.portfolio?portfolios.find(p=>p.id===params.portfolio)??null:null;
  if(params.account&&!account) redirect(`/app?tenant=${membership.tenant_id}`);
  if(params.portfolio&&!portfolio) redirect(`/app?tenant=${membership.tenant_id}`);
  const workspace=account?await getWorkspace(membership.tenant_id,account.id):null;
  return {me,membership,accounts,portfolios,account,portfolio,workspace,unreadCount:unread.length};
}
