export function StatusBadge({value}:{value:string}){const v=value.toLowerCase().replaceAll("_","-");return <span className={`status-badge status-${v}`}>{value.replaceAll("_"," ")}</span>}
