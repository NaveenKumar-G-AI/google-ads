export function money(micros: number, currency = "USD") {
  const amount = micros / 1_000_000;
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(amount); }
  catch { return `${currency} ${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}`; }
}
export function dateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
export function label(value: string | null | undefined) { return (value ?? "unknown").replaceAll("_", " "); }
