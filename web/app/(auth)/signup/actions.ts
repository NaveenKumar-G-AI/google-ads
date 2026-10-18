"use server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
export async function signUp(formData:FormData){
  const email=String(formData.get("email")??"").trim();
  const password=String(formData.get("password")??"");
  if(password.length<10) redirect(`/signup?error=${encodeURIComponent("Use at least 10 characters")}`);
  const h=await headers(); const origin=h.get("origin")||process.env.NEXT_PUBLIC_SITE_URL||"";
  const supabase=await createClient();
  const {data,error}=await supabase.auth.signUp({email,password,options:origin?{emailRedirectTo:`${origin}/api/auth/callback`}:undefined});
  if(error) redirect(`/signup?error=${encodeURIComponent("Sign-up failed")}`);
  if(data.session) redirect("/onboarding");
  redirect(`/login?message=${encodeURIComponent("Check your email to confirm your account, then sign in.")}`);
}
