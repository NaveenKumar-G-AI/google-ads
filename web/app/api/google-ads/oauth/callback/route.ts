import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
const API=process.env.RECOVERY_API_BASE_URL??"http://127.0.0.1:8000";
export async function GET(request:Request){
  const url=new URL(request.url); const error=url.searchParams.get("error");
  if(error) return NextResponse.redirect(new URL(`/onboarding?oauth_error=${encodeURIComponent(error)}`,url.origin));
  const code=url.searchParams.get("code"),state=url.searchParams.get("state");
  if(!code||!state) return NextResponse.redirect(new URL("/onboarding?oauth_error=missing_callback_parameters",url.origin));
  const supabase=await createClient(); const {data:claims}=await supabase.auth.getClaims(); const {data:session}=await supabase.auth.getSession();
  if(!claims?.claims?.sub||!session.session?.access_token) return NextResponse.redirect(new URL("/login",url.origin));
  const response=await fetch(`${API}/v1/onboarding/google-ads/oauth/callback`,{method:"POST",cache:"no-store",headers:{Authorization:`Bearer ${session.session.access_token}`,"Content-Type":"application/json"},body:JSON.stringify({code,state})});
  if(!response.ok){const body=await response.json().catch(()=>null);return NextResponse.redirect(new URL(`/onboarding?oauth_error=${encodeURIComponent(body?.error?.message??"google_ads_connection_failed")}`,url.origin));}
  const result=await response.json(); const target=new URL(result.return_path||"/onboarding",url.origin);target.searchParams.set("tenant",result.tenant_id);target.searchParams.set("discovery_job",result.discovery_job.job_id);return NextResponse.redirect(target);
}
