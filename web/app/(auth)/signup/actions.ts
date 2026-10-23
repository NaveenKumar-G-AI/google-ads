"use server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { recordMarketingEvent } from "@/lib/marketing-analytics-server";
import { authSiteOrigin } from "@/lib/auth-navigation";
export async function signUp(formData:FormData){
  const email=String(formData.get("email")??"").trim();
  const password=String(formData.get("password")??"");
  if (!email || email.length > 254) redirect(`/signup?error=${encodeURIComponent("Enter a valid email address.")}`);
  if(password.length<10) redirect(`/signup?error=${encodeURIComponent("Use at least 10 characters")}`);
  const h=await headers();
  recordMarketingEvent("signup_started","signup",h);
  if(!process.env.NEXT_PUBLIC_SUPABASE_URL||!process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) redirect(`/signup?error=${encodeURIComponent("Account registration is not available yet. Please try again later.")}`);
  let failed = false;
  let hasSession = false;
  try {
    const origin = authSiteOrigin(process.env.NEXT_PUBLIC_SITE_URL, h.get("origin") || "");
    const supabase = await createClient();
    const { data, error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: `${origin}/api/auth/callback` } });
    failed = !!error;
    // An obfuscated identity for an existing email is not a completed new signup.
    if (!error && data.user?.identities?.length) recordMarketingEvent("signup_completed", "signup", h);
    hasSession = !error && !!data.session;
  } catch {
    console.error("recovery_auth_signup_unavailable");
    failed = true;
  }
  if(failed) redirect(`/signup?error=${encodeURIComponent("Sign-up could not be completed. Please try again.")}`);
  if(hasSession) redirect("/onboarding");
  redirect(`/login?message=${encodeURIComponent("Check your email to confirm your account, then sign in.")}`);
}
