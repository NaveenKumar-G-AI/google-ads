"use server";
import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/recovery-api";

export async function startSync(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  const start=String(formData.get("start")),end=String(formData.get("end"));
  await apiFetch(`/v1/tenants/${tenant}/accounts/${account}/syncs`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({start,end})});
  revalidatePath("/dashboard/setup");
}
export async function saveTruth(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  const raw=String(formData.get("payload")??"");let payload:unknown;
  try{payload=JSON.parse(raw)}catch{throw new Error("Business Truth must be valid JSON")}
  await apiFetch(`/v1/tenants/${tenant}/accounts/${account}/business-truth`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({payload})});
  revalidatePath("/dashboard/setup");
}
export async function startAnalysis(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  const sync_run_id=String(formData.get("sync_run_id")),truth_snapshot_id=String(formData.get("truth_snapshot_id"));
  const as_of=String(formData.get("as_of")),conversion_lag_days=Number(formData.get("conversion_lag_days"));
  await apiFetch(`/v1/tenants/${tenant}/accounts/${account}/analyses`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({sync_run_id,truth_snapshot_id,as_of,conversion_lag_days})});
  revalidatePath("/dashboard/setup");
}
