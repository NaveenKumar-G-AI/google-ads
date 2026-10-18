"use server";
import { revalidatePath } from "next/cache";
import { saveMeasurementMapping } from "@/lib/recovery-api";
export async function saveMeasurementMappingAction(formData:FormData){
  const tenant=String(formData.get("tenant")||""),account=String(formData.get("account")||"");
  const resource=String(formData.get("conversion_action_resource")||"");
  const outcome=String(formData.get("outcome_id")||"")||null;
  await saveMeasurementMapping(tenant,account,resource,outcome);
  revalidatePath("/app/measurement-integrity");revalidatePath("/app/measurement-integrity/conversion-actions");
}
