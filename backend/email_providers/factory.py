import os
from email_providers.sendgrid_provider import SendGridEmailProvider
from email_providers.base import EmailProvider


def get_email_provider() -> EmailProvider:
    provider = os.getenv("EMAIL_PROVIDER", "sendgrid").lower().strip()

    if provider == "sendgrid":
        return SendGridEmailProvider()

    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {provider}")
