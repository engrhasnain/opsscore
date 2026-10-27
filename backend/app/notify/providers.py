"""Delivery providers. Each one sends a single message on one channel.

Providers raise ``DeliveryError``; ``permanent=True`` means retrying cannot
help (a malformed number, a rejected address), so the dispatcher stops.
"""

import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.enums import Channel

logger = logging.getLogger("opscore.notify")


class DeliveryError(Exception):
    def __init__(self, message: str, *, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class Provider(Protocol):
    def send(self, channel: Channel, recipient: str, subject: str, body: str) -> str | None:
        """Deliver and return the provider's message id, if it gives one."""


class LogProvider:
    """Development provider: writes the message to the log instead of sending it."""

    def send(self, channel: Channel, recipient: str, subject: str, body: str) -> str | None:
        logger.info(
            "notification (not sent, log provider)",
            extra={"channel": str(channel), "recipient": recipient, "subject": subject},
        )
        return f"log-{uuid.uuid4().hex[:12]}"


@dataclass
class SentMessage:
    channel: Channel
    recipient: str
    subject: str
    body: str


@dataclass
class MemoryProvider:
    """Test provider: records messages; can be told to fail."""

    sent: list[SentMessage] = field(default_factory=list)
    fail_with: DeliveryError | None = None

    def send(self, channel: Channel, recipient: str, subject: str, body: str) -> str | None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(SentMessage(channel, recipient, subject, body))
        return f"mem-{len(self.sent)}"


class SmtpProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, channel: Channel, recipient: str, subject: str, body: str) -> str | None:
        s = self.settings
        message = EmailMessage()
        message["From"] = s.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = f"<{uuid.uuid4().hex}@opscore>"
        message.set_content(body)
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as client:
                if s.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                if s.smtp_username and s.smtp_password:
                    client.login(s.smtp_username, s.smtp_password.get_secret_value())
                client.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise DeliveryError(f"recipient refused: {exc}", permanent=True) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise DeliveryError(f"SMTP error: {exc}") from exc
        return message["Message-ID"]


class TwilioProvider:
    """SMS and WhatsApp through Twilio's Messages API."""

    API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    MAX_BODY = 1600  # Twilio's limit for a single message

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=15)

    def send(self, channel: Channel, recipient: str, subject: str, body: str) -> str | None:
        s = self.settings
        if channel == Channel.WHATSAPP:
            if not s.twilio_whatsapp_from:
                raise DeliveryError("no WhatsApp sender configured", permanent=True)
            sender, to = f"whatsapp:{s.twilio_whatsapp_from}", f"whatsapp:{recipient}"
        else:
            if not s.twilio_sms_from:
                raise DeliveryError("no SMS sender configured", permanent=True)
            sender, to = s.twilio_sms_from, recipient
        text = body if len(body) <= self.MAX_BODY else body[: self.MAX_BODY - 1] + "…"
        try:
            response = self.client.post(
                self.API.format(sid=s.twilio_account_sid),
                data={"From": sender, "To": to, "Body": text},
                auth=(
                    s.twilio_account_sid or "",
                    s.twilio_auth_token.get_secret_value() if s.twilio_auth_token else "",
                ),
            )
        except httpx.HTTPError as exc:
            raise DeliveryError(f"Twilio unreachable: {exc}") from exc
        if response.status_code in (200, 201):
            return response.json().get("sid")
        transient = response.status_code == 429 or response.status_code >= 500
        raise DeliveryError(f"Twilio returned {response.status_code}: {response.text[:300]}", permanent=not transient)


class Router:
    """Picks the provider for a channel."""

    def __init__(self, email: Provider, sms: Provider, whatsapp: Provider):
        self._by_channel = {Channel.EMAIL: email, Channel.SMS: sms, Channel.WHATSAPP: whatsapp}

    def for_channel(self, channel: Channel) -> Provider:
        return self._by_channel[channel]

    @classmethod
    def everything(cls, provider: Provider) -> "Router":
        return cls(provider, provider, provider)


_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        settings = get_settings()
        email: Provider = SmtpProvider(settings) if settings.email_provider == "smtp" else LogProvider()
        sms: Provider = TwilioProvider(settings) if settings.sms_provider == "twilio" else LogProvider()
        _router = Router(email=email, sms=sms, whatsapp=sms)
    return _router


def set_router(router: Router | None) -> None:
    global _router
    _router = router
