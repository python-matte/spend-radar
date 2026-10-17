"""Sending. Email over SMTP and Slack through incoming webhooks.

Nothing here runs unless you pass --send to `spend-radar digest`. Secrets are read from
environment variables. The config file holds only the names of those variables, never the
secrets themselves.
"""

from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from pathlib import Path

from .digest import Message
from .schemas import NotifyConfig

SMTP_ENV = ("SPEND_RADAR_SMTP_HOST", "SPEND_RADAR_SMTP_USER", "SPEND_RADAR_SMTP_PASSWORD")
FROM_ENV = "SPEND_RADAR_FROM"
PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net")


class NotifyError(Exception):
    pass


def load_config(path: Path) -> NotifyConfig:
    try:
        return NotifyConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotifyError(f"Could not read the notify config {path}: {exc}") from exc


def preflight(
    messages: list[Message],
    env: Mapping[str, str],
    send_email: bool = True,
    send_slack: bool = True,
) -> list[str]:
    """Return every problem that would stop a real send. Empty means safe to go."""
    problems: list[str] = []
    for m in messages:
        domain = m.contact.email.rsplit("@", 1)[-1].lower()
        if send_email and domain in PLACEHOLDER_DOMAINS:
            problems.append(
                f"{m.contact.email} is a placeholder address. Copy the example config and use "
                "real addresses."
            )
    if send_email:
        problems += [
            f"Missing environment variable {n}" for n in (*SMTP_ENV, FROM_ENV) if not env.get(n)
        ]
    if send_slack:
        for m in messages:
            name = m.contact.slack_webhook_env
            if not name:
                problems.append(f"{m.recipient_key} has no slack_webhook_env in the config")
            elif not env.get(name):
                problems.append(f"Missing environment variable {name} for {m.recipient_key}")
    return sorted(set(problems))


class SmtpEmailSender:
    def __init__(
        self,
        env: Mapping[str, str],
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        self.env = env
        self.smtp_factory = smtp_factory

    def build(self, m: Message, dashboard_html: str | None) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.env[FROM_ENV]
        msg["To"] = f"{m.contact.name} <{m.contact.email}>"
        msg["Subject"] = m.subject
        msg.set_content(m.email_text())
        msg.add_alternative(m.email_html(), subtype="html")
        if m.attach_dashboard and dashboard_html:
            msg.add_attachment(
                dashboard_html.encode("utf-8"),
                maintype="text",
                subtype="html",
                filename="dashboard.html",
            )
        return msg

    def send(self, m: Message, dashboard_html: str | None) -> None:
        port = int(self.env.get("SPEND_RADAR_SMTP_PORT", "587"))
        msg = self.build(m, dashboard_html)
        with self.smtp_factory(self.env["SPEND_RADAR_SMTP_HOST"], port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.env["SPEND_RADAR_SMTP_USER"], self.env["SPEND_RADAR_SMTP_PASSWORD"])
            smtp.send_message(msg)


class SlackWebhookSender:
    def __init__(
        self,
        env: Mapping[str, str],
        opener: Callable[..., object] = urllib.request.urlopen,
    ) -> None:
        self.env = env
        self.opener = opener

    def send(self, m: Message) -> None:
        url = self.env[m.contact.slack_webhook_env or ""]
        body = json.dumps(m.slack_payload()).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            self.opener(req, timeout=15)
        except (urllib.error.URLError, OSError) as exc:
            raise NotifyError(f"Slack send failed for {m.recipient_key}: {exc}") from exc


def send_all(
    messages: list[Message],
    dashboard_html: str,
    env: Mapping[str, str] | None = None,
    email: SmtpEmailSender | None = None,
    slack: SlackWebhookSender | None = None,
) -> list[str]:
    """Check everything first, then send. Never sends part of a batch because of a config gap."""
    env = env if env is not None else os.environ
    problems = preflight(messages, env)
    if problems:
        raise NotifyError("Nothing was sent.\n- " + "\n- ".join(problems))
    email = email or SmtpEmailSender(env)
    slack = slack or SlackWebhookSender(env)
    sent: list[str] = []
    for m in messages:
        email.send(m, dashboard_html)
        slack.send(m)
        sent.append(m.recipient_key)
    return sent
