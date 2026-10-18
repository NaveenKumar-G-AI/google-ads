"use server";
import { redirect } from "next/navigation";
import { createBillingCheckout, reconcileBilling } from "@/lib/recovery-api";

export async function startCheckout(formData:FormData){const tenant=String(formData.get("tenant")||"");const plan=String(formData.get("plan_key")||"");if(!tenant||!plan)throw new Error("tenant and plan are required");const idem=`billing-${tenant}-${plan}-${crypto.randomUUID()}`;const r=await createBillingCheckout(tenant,plan,idem);if(r.checkout_url)redirect(r.checkout_url);redirect(`/dashboard/billing?tenant=${encodeURIComponent(tenant)}&created=1`);}
export async function reconcile(formData:FormData){const tenant=String(formData.get("tenant")||"");if(!tenant)throw new Error("tenant is required");await reconcileBilling(tenant);redirect(`/dashboard/billing?tenant=${encodeURIComponent(tenant)}&reconciled=1`);}
