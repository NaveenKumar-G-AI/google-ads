"use server";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
export async function signIn(formData: FormData) {
  const email=String(formData.get("email")??"").trim(); const password=String(formData.get("password")??"");
  const supabase=await createClient(); const {error}=await supabase.auth.signInWithPassword({email,password});
  if(error) redirect(`/login?error=${encodeURIComponent("Sign-in failed")}`); redirect("/onboarding");
}
