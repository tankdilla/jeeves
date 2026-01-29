from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class SendEmailRequest:
    to_email: str
    subject: str
    body_text: str
    from_email: str
    from_name: Optional[str] = None
    reply_to: Optional[str] = None


@dataclass
class SendEmailResult:
    provider: str
    provider_msg_id: str
    dry_run: bool


class EmailProvider(Protocol):
    def send_email(self, req: SendEmailRequest) -> SendEmailResult:
        ...
