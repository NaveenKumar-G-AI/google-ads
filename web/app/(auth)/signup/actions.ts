"use server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { recordMarketingEvent } from "@/lib/marketing-analytics-server";
export async function signUp(formData:FormData){
  const email=String(formData.get("email")??"").trim();
  const password=String(formData.get("password")??"");
  if(password.length<10) redirect(`/signup?error=${encodeURIComponent("Use at least 10 characters")}`);
  const h=await headers(); const origin=h.get("origin")||process.env.NEXT_PUBLIC_SITE_URL||"";
  recordMarketingEvent("signup_started","signup",h);
  if(!process.env.NEXT_PUBLIC_SUPABASE_URL||!process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) redirect(`/signup?error=${encodeURIComponent("Account registration is not available yet. Please try again later.")}`);
  const supabase=await createClient();
  const {data,error}=await supabase.auth.signUp({email,password,options:origin?{emailRedirectTo:`${origin}/api/auth/callback`}:undefined});
  if(error) redirect(`/signup?error=${encodeURIComponent("Sign-up failed")}`);
  // Supabase may return an obfuscated user with no identities for an existing email.
  // This means a new auth account was created, not email verification or activation.
  if(data.user&&data.user.identities&&data.user.identities.length>0) recordMarketingEvent("signup_completed","signup",h);
  if(data.session) redirect("/onboarding");
  redirect(`/login?message=${encodeURIComponent("Check your email to confirm your account, then sign in.")}`);
}
