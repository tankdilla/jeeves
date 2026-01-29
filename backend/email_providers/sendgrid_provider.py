import os
import uuid
from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To

from email_providers.base import SendEmailRequest, SendEmailResult


class SendGridEmailProvider:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")
        if not self.api_key:
            raise RuntimeError("SENDGRID_API_KEY is not set")

        self.client = SendGridAPIClient(self.api_key)

    def send_email(self, req: SendEmailRequest) -> SendEmailResult:
        dry_run = os.getenv("OUTREACH_DRY_RUN", "false").lower() == "true"
        test_email = os.getenv("OUTREACH_TEST_EMAIL")

        to_email = req.to_email
        if dry_run:
            if not test_email:
                raise RuntimeError("OUTREACH_TEST_EMAIL must be set when OUTREACH_DRY_RUN=true")
            to_email = test_email

        from_email = Email(req.from_email, req.from_name or "")
        to = To(to_email)

        mail = Mail(
            from_email=from_email,
            to_emails=to,
            subject=req.subject,
            plain_text_content=req.body_text,
        )

        if req.reply_to:
            mail.reply_to = Email(req.reply_to)

        # SendGrid doesn't always return a message id in the body.
        # We'll capture the X-Message-Id header when available, otherwise generate one.

        # response = self.client.send(mail)
        # msg_id = response.headers.get("X-Message-Id") or f"sg-fallback-{uuid.uuid4()}"

        try:
            response = self.client.send(mail)
            msg_id = response.headers.get("X-Message-Id") or f"sg-fallback-{uuid.uuid4()}"
        except HTTPError as e:
            # SendGrid returns useful JSON in the body for 403s
            raise RuntimeError(f"SendGrid error {e.status_code}: {e.body.decode('utf-8') if hasattr(e.body, 'decode') else e.body}")

        return SendEmailResult(provider="sendgrid", provider_msg_id=msg_id, dry_run=dry_run)
