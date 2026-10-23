"use server";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
export async function signIn(formData: FormData) {
  const email=String(formData.get("email")??"").trim(); const password=String(formData.get("password")??"");
  if (!email || !password || email.length > 254) redirect(`/login?error=${encodeURIComponent("Enter your email and password.")}`);
  let failure = "";
  try {
    const supabase = await createClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) failure = "Sign-in failed. Check your email and password.";
  } catch {
    console.error("recovery_auth_signin_unavailable");
    failure = "Sign-in is temporarily unavailable. Please try again.";
  }
  if (failure) redirect(`/login?error=${encodeURIComponent(failure)}`);
  redirect("/onboarding");
}
