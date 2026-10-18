from __future__ import annotations

from datetime import date
from email.message import EmailMessage
import os
import smtplib
import ssl
from typing import Any
from uuid import UUID

from recovery.api.repository import PostgresApiRepository
from recovery.db.postgres import PostgresRecoveryRepository
from recovery.worker.domain import ClaimedJob, JobSuccess, PermanentWorkerError


class ReportGenerationJobRunner:
    """Generate one immutable report snapshot and its static artifacts.

    Scheduled email delivery is deliberately non-retrying after SMTP handoff begins:
    if the provider outcome is ambiguous we record ambiguity and keep the generated
    report, rather than risking duplicate client emails.
    """

    def __init__(self, *, core: PostgresRecoveryRepository) -> None:
        self.repo=PostgresApiRepository(core)

    @staticmethod
    def _date(v: Any) -> date | None:
        return date.fromisoformat(str(v)) if v else None

    @staticmethod
    def _smtp_config() -> dict[str, Any] | None:
        host=os.environ.get("REPORT_SMTP_HOST","").strip()
        sender=os.environ.get("REPORT_SMTP_FROM","").strip()
        if not host or not sender:
            return None
        return {
            "host":host,
            "port":int(os.environ.get("REPORT_SMTP_PORT","587")),
            "username":os.environ.get("REPORT_SMTP_USERNAME","").strip() or None,
            "password":os.environ.get("REPORT_SMTP_PASSWORD","") or None,
            "from":sender,
            "mode":os.environ.get("REPORT_SMTP_TLS_MODE","starttls").strip().lower(),
        }

    @staticmethod
    def _deliver(*, config: dict[str, Any], recipient: str, subject: str, body: str, pdf: bytes, filename: str) -> dict[str,str]:
        msg=EmailMessage();msg["From"]=config["from"];msg["To"]=recipient;msg["Subject"]=subject
        msg.set_content(body)
        msg.add_attachment(pdf,maintype="application",subtype="pdf",filename=filename)
        context=ssl.create_default_context()
        mode=config["mode"]
        if mode=="ssl":
            smtp=smtplib.SMTP_SSL(config["host"],config["port"],timeout=30,context=context)
        elif mode in {"starttls","plain"}:
            smtp=smtplib.SMTP(config["host"],config["port"],timeout=30)
            smtp.ehlo()
            if mode=="starttls": smtp.starttls(context=context); smtp.ehlo()
        else:
            raise ValueError("REPORT_SMTP_TLS_MODE must be starttls, ssl, or plain")
        with smtp:
            if config["username"]:
                smtp.login(config["username"],config["password"] or "")
            refused=smtp.send_message(msg, to_addrs=[recipient])
        return {str(k):str(v) for k,v in refused.items()}

    def __call__(self, job: ClaimedJob) -> JobSuccess:
        p=job.payload
        try:
            generation=self.repo.generate_report(
                tenant_id=job.tenant_id,generated_by=job.requested_by,
                report_type=str(p["report_type"]),scope_kind=str(p["scope_kind"]),scope_id=str(p["scope_id"]),
                period_start=self._date(p.get("period_start")),period_end=self._date(p.get("period_end")),
                source_job_id=job.job_id,schedule_id=UUID(str(p["schedule_id"])) if p.get("schedule_id") else None,
            )
        except (KeyError,ValueError) as exc:
            raise PermanentWorkerError(str(exc),code="REPORT_INVALID") from exc

        generation_id=UUID(str(generation["id"])); schedule_id=UUID(str(p["schedule_id"])) if p.get("schedule_id") else None
        delivery={"scheduled":bool(schedule_id),"sent":0,"failed":0,"ambiguous":0,"skipped":0}
        if schedule_id:
            schedule=self.repo.report_schedule(tenant_id=job.tenant_id,schedule_id=schedule_id)
            recipients=[str(x) for x in schedule.get("recipients") or []]
            email_gate=getattr(self.repo,"internal_feature_enabled",None)
            if email_gate is not None and not email_gate(tenant_id=job.tenant_id,feature_key="scheduled_report_email"):
                for recipient in recipients:
                    self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="skipped_not_configured",detail="Scheduled report email disabled by platform operational control")
                delivery["skipped"]+=len(recipients)
                recipients=[]
            if recipients:
                cfg=self._smtp_config()
                pdf=self.repo.report_artifact(tenant_id=job.tenant_id,generation_id=generation_id,artifact_format="pdf")
                prior=self.repo.report_generation(tenant_id=job.tenant_id,generation_id=generation_id).get("deliveries") or []
                latest_by_recipient={}
                for event in prior:
                    latest_by_recipient[str(event.get("recipient"))]=str(event.get("event_type"))
                for recipient in recipients:
                    previous=latest_by_recipient.get(recipient)
                    if previous in {"sent","failed","ambiguous","skipped_not_configured"}:
                        delivery["skipped"]+=1
                        continue
                    if previous=="prepared":
                        self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="ambiguous",detail="Previous delivery attempt ended after prepared state without a terminal audit event; not retried.")
                        delivery["ambiguous"]+=1
                        continue
                    if cfg is None:
                        self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="skipped_not_configured",detail="REPORT_SMTP_HOST/REPORT_SMTP_FROM not configured")
                        delivery["skipped"]+=1
                        continue
                    self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="prepared",detail=None)
                    try:
                        refused=self._deliver(
                            config=cfg,recipient=recipient,
                            subject=f"Recovery OS - {generation['report_type'].replace('_',' ').title()}",
                            body="Attached is an immutable Recovery OS report snapshot. Financial evidence classes in the report are non-additive; verified recovery requires causal evidence.",
                            pdf=bytes(pdf["content"]),filename=f"recovery-os-{generation['report_type']}-{str(generation_id)[:8]}.pdf",
                        )
                    except Exception as exc:
                        # Outcome for this recipient can be ambiguous after SMTP DATA. Never auto-retry it.
                        detail=f"SMTP outcome ambiguous: {type(exc).__name__}: {str(exc)[:500]}"
                        self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="ambiguous",detail=detail)
                        delivery["ambiguous"]+=1
                    else:
                        if recipient in refused:
                            self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="failed",detail=refused[recipient][:1000])
                            delivery["failed"]+=1
                        else:
                            self.repo.record_report_delivery(tenant_id=job.tenant_id,generation_id=generation_id,schedule_id=schedule_id,recipient=recipient,event_type="sent",detail=None)
                            delivery["sent"]+=1

        return JobSuccess(result={"generation_id":str(generation_id),"snapshot_sha256":generation["snapshot_sha256"],"delivery":delivery})
