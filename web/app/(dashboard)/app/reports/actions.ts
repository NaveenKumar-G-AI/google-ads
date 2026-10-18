"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { saveReportSchedule,startReportGeneration,revokeReportShare } from "@/lib/recovery-api";
const key=(p:string)=>`${p}-${crypto.randomUUID()}`;

export async function generateReportAction(formData:FormData){
  const tenant=String(formData.get("tenant")),report_type=String(formData.get("report_type")),scope_kind=String(formData.get("scope_kind")),scope_id=String(formData.get("scope_id"));
  const period_start=String(formData.get("period_start")||"")||null,period_end=String(formData.get("period_end")||"")||null;
  const job=await startReportGeneration(tenant,{report_type,scope_kind,scope_id,period_start,period_end},key("report"));
  redirect(`/app/reports?tenant=${encodeURIComponent(tenant)}&queued=${encodeURIComponent(job.job_id)}`)
}

export async function saveReportScheduleAction(formData:FormData){
  const tenant=String(formData.get("tenant"));
  const recipients=String(formData.get("recipients")||"").split(/[;,\n]/).map(x=>x.trim()).filter(Boolean);
  const payload={schedule_id:String(formData.get("schedule_id")||"")||null,report_type:String(formData.get("report_type")),scope_kind:String(formData.get("scope_kind")),scope_id:String(formData.get("scope_id")),frequency:String(formData.get("frequency")),timezone_name:String(formData.get("timezone_name")),hour:Number(formData.get("hour")),minute:Number(formData.get("minute")),weekday:String(formData.get("weekday")||"")===""?null:Number(formData.get("weekday")),day_of_month:String(formData.get("day_of_month")||"")===""?null:Number(formData.get("day_of_month")),recipients,enabled:String(formData.get("enabled")||"true")==="true"};
  await saveReportSchedule(tenant,payload);revalidatePath("/app/reports/schedules");
}

export async function revokeReportShareAction(formData:FormData){const tenant=String(formData.get("tenant")),share=String(formData.get("share")),generation=String(formData.get("generation"));await revokeReportShare(tenant,share);revalidatePath(`/app/reports/${generation}`)}
