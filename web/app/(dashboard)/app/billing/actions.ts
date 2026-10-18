"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { cancelBillingAtCycleEnd,cancelBillingPlanChange,createBillingCheckout,reconcileBilling,refreshBillingInvoices,releaseBillingAccountSlot,saveBillingProfile,scheduleBillingPlanChange } from "@/lib/recovery-api";
const idem=(prefix:string)=>`${prefix}-${crypto.randomUUID()}`;
const billingUrl=(tenant:string,extra="")=>`/app/billing?tenant=${encodeURIComponent(tenant)}${extra}`;

export async function startCheckoutAction(formData:FormData){const tenant=String(formData.get("tenant")||""),plan=String(formData.get("plan_key")||"");if(!tenant||!plan)throw new Error("tenant and plan are required");const r=await createBillingCheckout(tenant,plan,idem("billing-checkout"));if(r.checkout_url)redirect(r.checkout_url);redirect(billingUrl(tenant,"&created=1"))}
export async function reconcileBillingAction(formData:FormData){const tenant=String(formData.get("tenant")||"");await reconcileBilling(tenant);revalidatePath("/app/billing");redirect(billingUrl(tenant,"&reconciled=1"))}
export async function previewPlanAction(formData:FormData){const tenant=String(formData.get("tenant")||""),plan=String(formData.get("target_plan_key")||"");redirect(billingUrl(tenant,`&preview=${encodeURIComponent(plan)}`))}
export async function schedulePlanChangeAction(formData:FormData){const tenant=String(formData.get("tenant")||""),plan=String(formData.get("target_plan_key")||"");await scheduleBillingPlanChange(tenant,plan,idem("billing-plan-change"));revalidatePath("/app/billing");redirect(billingUrl(tenant,"&plan_change=scheduled"))}
export async function cancelPlanChangeAction(formData:FormData){const tenant=String(formData.get("tenant")||"");await cancelBillingPlanChange(tenant,idem("billing-plan-change-cancel"));revalidatePath("/app/billing");redirect(billingUrl(tenant,"&plan_change=cancelled"))}
export async function cancelSubscriptionAction(formData:FormData){const tenant=String(formData.get("tenant")||"");await cancelBillingAtCycleEnd(tenant,idem("billing-cancel"));revalidatePath("/app/billing");redirect(billingUrl(tenant,"&cancellation=scheduled"))}
export async function refreshInvoicesAction(formData:FormData){const tenant=String(formData.get("tenant")||"");await refreshBillingInvoices(tenant);revalidatePath("/app/billing");redirect(billingUrl(tenant,"&invoices=refreshed"))}
export async function saveBillingProfileAction(formData:FormData){const tenant=String(formData.get("tenant")||"");await saveBillingProfile(tenant,{legal_name:String(formData.get("legal_name")||""),billing_email:String(formData.get("billing_email")||""),tax_country:String(formData.get("tax_country")||""),tax_region:String(formData.get("tax_region")||"")||null,gstin:String(formData.get("gstin")||"")||null});revalidatePath("/app/billing");redirect(billingUrl(tenant,"&profile=saved"))}
export async function releaseSlotAction(formData:FormData){const tenant=String(formData.get("tenant")||""),account=String(formData.get("account_id")||"");await releaseBillingAccountSlot(tenant,account);revalidatePath("/app/billing");redirect(billingUrl(tenant,"&slot=released"))}
