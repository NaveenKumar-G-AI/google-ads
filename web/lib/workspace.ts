import { redirect } from "next/navigation";
import { getAccounts, getMe, getWorkspace } from "@/lib/recovery-api";

export async function resolveWorkspace(params: { tenant?: string; account?: string }) {
  const me = await getMe();
  const membership = params.tenant ? me.memberships.find(m => m.tenant_id === params.tenant) : me.memberships[0];
  if (!membership) return { me, membership: null, accounts: [], account: null, workspace: null };
  const accounts = await getAccounts(membership.tenant_id);
  const account = params.account ? accounts.find(a => a.id === params.account) : accounts[0];
  if (!account && accounts.length) redirect(`/dashboard?tenant=${membership.tenant_id}&account=${accounts[0].id}`);
  const workspace = account ? await getWorkspace(membership.tenant_id, account.id) : null;
  return { me, membership, accounts, account: account ?? null, workspace };
}
