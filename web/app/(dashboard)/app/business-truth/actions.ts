"use server";
import { revalidatePath } from "next/cache";
import { saveGuidedBusinessTruth } from "@/lib/recovery-api";
const lines=(v:FormDataEntryValue|null)=>String(v??"").split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
const aliases=(v:string)=>v.split(",").map(x=>x.trim()).filter(Boolean);
const policyKeys=["support","training","informational","research","competitor","second_hand","rental","repair","wholesale"];
export async function saveBusinessTruthAction(formData:FormData){
 const tenant=String(formData.get("tenant")),account=String(formData.get("account"));
 const offers=lines(formData.get("offers")).map(row=>{const [name,description,...rest]=row.split("|").map(x=>x.trim());return {name,description:description||`Confirmed service offered by the business: ${name}`,aliases:aliases(rest.join("|"))}});
 const non_offers=lines(formData.get("non_offers")).map(row=>{const [name,reason,...rest]=row.split("|").map(x=>x.trim());return {name,reason:reason||`The business explicitly does not offer ${name}`,aliases:aliases(rest.join("|"))}});
 const service_areas=lines(formData.get("service_areas")).map(row=>{const [display_name,country_code,region,city,postal_code]=row.split("|").map(x=>x.trim());return {display_name,country_code,region:region||null,city:city||null,postal_code:postal_code||null}});
 const audience_policies=lines(formData.get("audiences")).map(row=>{const [name,disposition,reason,...rest]=row.split("|").map(x=>x.trim());return {name,disposition:disposition||"unknown",reason:reason||`Audience rule for ${name}`,aliases:aliases(rest.join("|")),condition:disposition==="conditional"?"Requires contextual review":null}});
 const protected_queries=lines(formData.get("protected_queries")).map(row=>{const [query,...reasonParts]=row.split("|").map(x=>x.trim());return {query,reason:reasonParts.join("|")||"Business-confirmed query must remain eligible"}});
 const additional_intent_policies:Object=Object.fromEntries(policyKeys.map(k=>[k,String(formData.get(`intent_${k}`)||"unknown")]));
 await saveGuidedBusinessTruth(tenant,account,{
   business_name:String(formData.get("business_name")||"").trim(),offers,non_offers,service_areas,
   catalog_complete:formData.get("catalog_complete")==="on",employment_policy:String(formData.get("intent_employment")||"unknown"),free_policy:String(formData.get("intent_free")||"unknown"),diy_policy:String(formData.get("intent_diy")||"unknown"),additional_intent_policies,
   audience_policies,geo_requirement:String(formData.get("geo_requirement")||"destination_or_job_must_be_in_service_area"),geo_condition:String(formData.get("geo_condition")||"").trim()||null,
   primary_outcomes:lines(formData.get("primary_outcomes")),supporting_outcomes:lines(formData.get("supporting_outcomes")),invalid_outcomes:lines(formData.get("invalid_outcomes")),protected_queries,
 },crypto.randomUUID());
 revalidatePath("/app/business-truth");revalidatePath("/app");
}
