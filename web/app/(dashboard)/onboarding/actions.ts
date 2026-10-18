"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import {
  createOrganization, createBillingCheckout, reconcileBilling, startGoogleAdsOAuth,
  selectGoogleAdsAccounts, saveGuidedBusinessTruth, saveMeasurementProfile,
  startAccountSync, startAccountAnalysis, completeOnboarding,
} from "@/lib/recovery-api";

const lines=(v:FormDataEntryValue|null)=>String(v??"").split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
const message=(e:unknown)=>e instanceof Error?e.message.slice(0,300):"The operation could not be completed";
function onboardingUrl(tenant?:string, account?:string, error?:string){const p=new URLSearchParams();if(tenant)p.set("tenant",tenant);if(account)p.set("account",account);if(error)p.set("setup_error",error);return `/onboarding${p.size?`?${p}`:""}`}
async function safe<T>(fn:()=>Promise<T>,tenant?:string,account?:string):Promise<T>{try{return await fn()}catch(e){redirect(onboardingUrl(tenant,account,message(e)))}}

export async function createOrganizationAction(formData:FormData){
  const name=String(formData.get("display_name")??"").trim();
  const slug=String(formData.get("slug")??"").trim()||null;
  const accepted=String(formData.get("accept_legal")||"")==="on";
  const terms=accepted?String(formData.get("terms_version")||"").trim()||null:null;
  const privacy=accepted?String(formData.get("privacy_version")||"").trim()||null:null;
  const turnstile=String(formData.get("cf-turnstile-response")||"").trim()||null;
  const result=await safe(()=>turnstile?createOrganization(name,slug,crypto.randomUUID(),accepted,terms,privacy,turnstile):createOrganization(name,slug,crypto.randomUUID(),accepted,terms,privacy));
  redirect(`/onboarding?tenant=${result.tenant_id}`);
}

export async function subscribeAction(formData:FormData){
  const tenant=String(formData.get("tenant")); const plan=String(formData.get("plan_key"));
  const checkout=await safe(()=>createBillingCheckout(tenant,plan,crypto.randomUUID()),tenant);
  if(!checkout.checkout_url) redirect(onboardingUrl(tenant,undefined,"Billing provider did not return a hosted checkout URL"));
  redirect(checkout.checkout_url);
}

export async function reconcileBillingAction(formData:FormData){
  const tenant=String(formData.get("tenant"));
  await safe(()=>reconcileBilling(tenant),tenant);
  revalidatePath("/onboarding");
  redirect(`/onboarding?tenant=${tenant}`);
}

export async function connectGoogleAdsAction(formData:FormData){
  const tenant=String(formData.get("tenant")); const email=String(formData.get("email")??"").trim();
  const result=await safe(()=>startGoogleAdsOAuth(tenant,`/onboarding?tenant=${encodeURIComponent(tenant)}`,email||null),tenant);
  redirect(result.authorization_url);
}

export async function selectAccountsAction(formData:FormData){
  const tenant=String(formData.get("tenant"));
  const ids=formData.getAll("customer_id").map(String).filter(Boolean);
  await safe(()=>selectGoogleAdsAccounts(tenant,ids),tenant);
  revalidatePath("/onboarding");
  redirect(`/onboarding?tenant=${tenant}`);
}

export async function saveGuidedTruthAction(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  const offerRows=lines(formData.get("offers")).map((row)=>{const [name,description,...aliasParts]=row.split("|").map(x=>x.trim());return {name,description:description||`Confirmed service offered by the business: ${name}`,aliases:aliasParts.join("|").split(",").map(x=>x.trim()).filter(Boolean)}});
  const nonOffers=lines(formData.get("non_offers")).map((row)=>{const [name,reason,...aliasParts]=row.split("|").map(x=>x.trim());return {name,reason:reason||`The business explicitly does not offer ${name}`,aliases:aliasParts.join("|").split(",").map(x=>x.trim()).filter(Boolean)}});
  const serviceAreas=lines(formData.get("service_areas")).map((row)=>{const [display_name,country_code,region,city,postal_code]=row.split("|").map(x=>x.trim());return {display_name,country_code,region:region||null,city:city||null,postal_code:postal_code||null}});
  const outcomes=lines(formData.get("primary_outcomes"));
  await safe(()=>saveGuidedBusinessTruth(tenant,account,{
    business_name:String(formData.get("business_name")??"").trim(),offers:offerRows,non_offers:nonOffers,service_areas:serviceAreas,
    catalog_complete:formData.get("catalog_complete")==="on",employment_policy:String(formData.get("employment_policy")||"unknown"),
    free_policy:String(formData.get("free_policy")||"unknown"),diy_policy:String(formData.get("diy_policy")||"unknown"),primary_outcomes:outcomes,
  },crypto.randomUUID()),tenant,account);
  revalidatePath("/onboarding"); redirect(`/onboarding?tenant=${tenant}&account=${account}`);
}

export async function saveMeasurementAction(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  await safe(()=>saveMeasurementProfile(tenant,account,Number(formData.get("conversion_lag_days"))),tenant,account);
  revalidatePath("/onboarding"); redirect(`/onboarding?tenant=${tenant}&account=${account}`);
}

export async function startFirstSyncAction(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  const result=await safe(()=>startAccountSync(tenant,account,String(formData.get("start")),String(formData.get("end")),crypto.randomUUID()),tenant,account);
  redirect(`/onboarding?tenant=${tenant}&account=${account}&job=${result.job_id}`);
}

export async function startFirstAnalysisAction(formData:FormData){
  const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
  const result=await safe(()=>startAccountAnalysis(tenant,account,{
    sync_run_id:String(formData.get("sync_run_id")),truth_snapshot_id:String(formData.get("truth_snapshot_id")),
    as_of:String(formData.get("as_of")),conversion_lag_days:Number(formData.get("conversion_lag_days")),
  },crypto.randomUUID()),tenant,account);
  redirect(`/onboarding?tenant=${tenant}&account=${account}&job=${result.job_id}`);
}

export async function finishOnboardingAction(formData:FormData){
  const tenant=String(formData.get("tenant")); await safe(()=>completeOnboarding(tenant),tenant); redirect(`/app?tenant=${tenant}`);
}
