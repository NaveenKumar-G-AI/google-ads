import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const metadata = { title: "Connect Google Ads | Recovery OS", robots: { index: false, follow: false } };

export default async function Connect() {
  // Public previews remain usable before credentials are configured.
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) {
    redirect("/signup?intent=connect");
  }
  let signedIn = false;
  try {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.getClaims();
    signedIn = !error && Boolean(data?.claims?.sub);
  } catch { /* Failed session checks return to signup/sign-in, never skip authorization. */ }
  redirect(signedIn ? "/onboarding" : "/signup?intent=connect");
}
