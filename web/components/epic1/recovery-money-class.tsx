import { money } from "@/lib/format";
export function RecoveryMoneyClass({label,value,currency,kind,note}:{label:string;value:number;currency:string;kind:"candidate"|"projection"|"observed"|"verified";note:string}){return <article className={`recovery-money-class recovery-${kind}`}><span>{label}</span><strong>{money(value,currency)}</strong><p>{note}</p></article>}
