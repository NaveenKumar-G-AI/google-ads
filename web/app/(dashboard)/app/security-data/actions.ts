"use server";
import { revalidatePath } from "next/cache";import { createDataRequest,cancelDataRequest } from "@/lib/recovery-api";
export async function createDataRequestAction(formData:FormData){const tenant=String(formData.get("tenant")),request_type=String(formData.get("request_type")),account_id=String(formData.get("account_id")||"")||null,reason=String(formData.get("reason")||"").trim();await createDataRequest(tenant,{request_type,account_id,reason});revalidatePath("/app/security-data")}
export async function cancelDataRequestAction(formData:FormData){const tenant=String(formData.get("tenant")),id=String(formData.get("request_id"));await cancelDataRequest(tenant,id);revalidatePath("/app/security-data")}
