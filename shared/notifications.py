"""SMTP-based job-completion notifications (R1.c).

Optional opt-in feature: when a job transitions to COMPLETED or FAILED, send
a single plain-text email summarising the result, the input files, and links
to the monitoring page (and dashboard, on success). Sender is
``noreply.grinn@bio-cloud.site`` (or whatever ``SMTP_FROM_ADDR`` is set to);
delivery is via SMTP relay through the operator's existing mailbox.

Reads SMTP_* config from `shared.config`. Pure stdlib (smtplib +
email.message). Failures NEVER raise into the caller — a missed email
must not poison the job's COMPLETED/FAILED state.

Both STARTTLS (port 587) and implicit TLS (port 465) are supported; the
helper branches on `cfg.smtp_port`. Anonymous SMTP (no auth) is also
allowed: if `smtp_user` / `smtp_password` are empty, the login step is
skipped — useful for relay-only setups.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable, Optional

try:
    # Backend / Celery context: repo root on sys.path → shared is a package.
    from shared.config import get_config
except ImportError:
    # Frontend context: shared/ itself is on sys.path → bare-name import.
    from config import get_config

log = logging.getLogger(__name__)


def send_job_complete_email(
    *,
    to_addr: str,
    job_id: str,
    status: str,                    # 'COMPLETED' or 'FAILED'
    input_filenames: Iterable[str],
    monitor_url: str,
    dashboard_url: Optional[str],   # None unless status == 'COMPLETED'
    error_summary: Optional[str],   # short, only on FAILED
) -> None:
    """Send the job-completion email via SMTP. Best-effort; never raises.

    Short-circuits silently if SMTP_HOST is unset or the recipient address
    is empty (i.e. feature disabled or user did not opt in).
    """
    cfg = get_config()
    if not cfg.smtp_host or not to_addr:
        return  # feature disabled or no recipient — silent no-op

    files_block = "\n".join(f"  - {f}" for f in input_filenames) or "  (none)"

    body_lines = [
        "Hello,",
        "",
        "Your gRINN job has finished.",
        "",
        f"  Job ID:   {job_id}",
        f"  Status:   {status}",
        "",
        "Input files:",
        files_block,
        "",
        "Monitor / download results:",
        f"  {monitor_url}",
    ]
    if status == "COMPLETED" and dashboard_url:
        body_lines += [
            "",
            "Interactive dashboard:",
            f"  {dashboard_url}",
        ]
    if status == "FAILED" and error_summary:
        body_lines += [
            "",
            "Error summary:",
            "  " + error_summary.replace("\n", "\n  "),
        ]
    body_lines += [
        "",
        "Note: Result files are retained for 72 hours after completion.",
        "",
        "—",
        "gRINN Web Service",
        "https://grinn.bio-cloud.site",
        "This is an automated message; please do not reply.",
    ]

    msg = EmailMessage()
    msg["From"] = cfg.smtp_from_addr
    msg["To"] = to_addr
    msg["Subject"] = f"gRINN job {job_id} {status}"
    msg.set_content("\n".join(body_lines))

    try:
        if cfg.smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=10, context=ctx) as s:
                if cfg.smtp_user and cfg.smtp_password:
                    s.login(cfg.smtp_user, cfg.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
                if cfg.smtp_user and cfg.smtp_password:
                    s.login(cfg.smtp_user, cfg.smtp_password)
                s.send_message(msg)
        # Log job_id only — never the recipient (PII).
        log.info("Sent job-completion email for job %s (%s)", job_id, status)
    except Exception as e:
        log.warning("Email notification failed for job %s: %s", job_id, e)
        # Deliberately swallow: the job's terminal status must not depend
        # on email delivery succeeding.
