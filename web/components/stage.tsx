import type { WorkspaceStage } from "@/lib/types";
import { dateTime, label } from "@/lib/format";
export function Stage({name,stage}:{name:string;stage:WorkspaceStage}){const cls=stage.status==="completed"||stage.status==="available"?"good":stage.status==="failed"?"bad":"warn";return <div className="stage"><div><strong>{name}</strong><small>{stage.completed_at?`Completed ${dateTime(stage.completed_at)}`:stage.started_at?`Started ${dateTime(stage.started_at)}`:"Not available yet"}</small></div><span className={`pill ${cls}`}>{label(stage.status)}</span></div>}
