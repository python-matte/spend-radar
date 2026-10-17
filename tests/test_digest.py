"""Monthly digest: snapshots, routing, dry run, and the guards on sending."""

from __future__ import annotations

import json
import smtplib
from datetime import date
from pathlib import Path

from spend_radar import core_logic as cl
from spend_radar.cli import main
from spend_radar.dashboard import render_dashboard
from spend_radar.digest import (
    build_digest,
    load_previous_snapshot,
    save_snapshot,
    write_dry_run,
)
from spend_radar.loader import AS_OF
from spend_radar.notify import (
    FROM_ENV,
    NotifyError,
    SlackWebhookSender,
    SmtpEmailSender,
    load_config,
    preflight,
    send_all,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "notify.example.json"
LAST_MONTH = date(2026, 9, 17)


def _last_month_snapshot(vendors):
    return cl.make_snapshot(vendors, cl.analyze(vendors, LAST_MONTH))


def test_diff_finds_what_changed_since_last_month(vendors, analysis):
    changes = cl.diff_snapshots(_last_month_snapshot(vendors), cl.make_snapshot(vendors, analysis))
    kinds = {c.vendor: c.kind for c in changes}
    assert kinds["Boardwick"] == "window_closed"
    assert kinds["Taskwave"] == "new_now"
    assert kinds["Meetly"] == "new_now"
    assert changes[0].kind == "window_closed"  # most serious first


def test_first_run_has_nothing_to_compare(vendors, analysis):
    assert cl.diff_snapshots(None, cl.make_snapshot(vendors, analysis)) == []


def test_a_renewal_that_removed_auto_renew_is_reported_as_a_win(vendors, analysis):
    before = cl.make_snapshot(vendors, analysis)
    after = before.model_copy(deep=True)
    entry = after.vendors["Taskwave"]
    entry.renewal_date = date(2027, 12, 20)
    entry.auto_renew = False
    (change,) = [c for c in cl.diff_snapshots(before, after) if c.vendor == "Taskwave"]
    assert change.kind == "renewed"
    assert "Auto-renew was removed" in change.text


def test_snapshots_round_trip_and_previous_is_the_latest_earlier_one(tmp_path, vendors):
    old = _last_month_snapshot(vendors)
    save_snapshot(tmp_path, old)
    assert load_previous_snapshot(tmp_path, AS_OF).as_of == LAST_MONTH
    assert load_previous_snapshot(tmp_path, LAST_MONTH) is None  # nothing earlier than itself


def _messages(vendors, analysis):
    previous = _last_month_snapshot(vendors)
    changes = cl.diff_snapshots(previous, cl.make_snapshot(vendors, analysis))
    return build_digest(vendors, analysis, changes, load_config(CONFIG), previous)


def test_owner_gets_everything_and_each_team_only_its_own_vendors(vendors, analysis):
    by_key = {m.recipient_key: m for m in _messages(vendors, analysis)}
    owner = by_key["default-owner"].email_text()
    for name in ("Taskwave", "Meetly", "Boardwick", "Cloudpebble"):
        assert name in owner
    assert by_key["default-owner"].attach_dashboard is True

    engineering = by_key["team-engineering"].email_text()
    assert "Taskwave" in engineering
    assert "Meetly" not in engineering and "Boardwick" not in engineering
    assert by_key["team-engineering"].attach_dashboard is False


def test_teams_with_nothing_due_get_no_message_and_missing_contacts_are_named(vendors, analysis):
    messages = _messages(vendors, analysis)
    keys = {m.recipient_key for m in messages}
    assert "team-facilities" not in keys  # no contact configured, and nothing due
    owner = next(m for m in messages if m.recipient_key == "default-owner").email_text()
    assert "Facilities" in owner and "No team contact is configured" in owner


def test_dry_run_writes_files_and_slack_payload_is_valid_json(tmp_path, vendors, analysis):
    messages = _messages(vendors, analysis)
    written = write_dry_run(messages, tmp_path, render_dashboard(vendors, analysis))
    assert (tmp_path / "dashboard.html").exists()
    payload = json.loads((tmp_path / "default-owner" / "slack.json").read_text())
    assert payload["blocks"][0]["type"] == "header"
    assert all(len(b["text"]["text"]) <= 3000 for b in payload["blocks"] if b["type"] == "section")
    assert len(written) == 1 + 3 * len(messages)
    assert "—" not in "".join(p.read_text() for p in written if p.suffix != ".html")


# Sending guards ----------------------------------------------------------------------------


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


REAL_ENV = {
    "SPEND_RADAR_SMTP_HOST": "smtp.test.invalid",
    "SPEND_RADAR_SMTP_USER": "user",
    "SPEND_RADAR_SMTP_PASSWORD": "pw",
    FROM_ENV: "radar@company.test",
}


def _real_address_messages(vendors, analysis):
    messages = _messages(vendors, analysis)
    for m in messages:
        m.contact = m.contact.model_copy(
            update={"email": m.contact.email.replace("example.com", "company.test")}
        )
    return messages


def test_preflight_refuses_placeholder_addresses_and_missing_secrets(vendors, analysis):
    problems = preflight(_messages(vendors, analysis), {})
    text = "\n".join(problems)
    assert "placeholder address" in text
    assert "SPEND_RADAR_SMTP_HOST" in text
    assert "SPEND_RADAR_SLACK_WEBHOOK" in text


def test_send_all_sends_nothing_if_any_check_fails(vendors, analysis):
    FakeSMTP.sent = []
    posted: list = []
    env = {**REAL_ENV}  # no Slack webhooks set
    messages = _real_address_messages(vendors, analysis)
    try:
        send_all(
            messages,
            "<html></html>",
            env,
            SmtpEmailSender(env, FakeSMTP),
            SlackWebhookSender(env, lambda *a, **k: posted.append(a)),
        )
    except NotifyError as exc:
        assert "Nothing was sent" in str(exc)
    else:
        raise AssertionError("expected NotifyError")
    assert FakeSMTP.sent == [] and posted == []


def test_send_all_with_a_complete_setup_uses_the_injected_senders(vendors, analysis):
    FakeSMTP.sent = []
    posted: list = []
    messages = _real_address_messages(vendors, analysis)
    env = {**REAL_ENV}
    for m in messages:
        env[m.contact.slack_webhook_env] = "https://hooks.test.invalid/abc"
    sent = send_all(
        messages,
        "<html>dash</html>",
        env,
        SmtpEmailSender(env, FakeSMTP),
        SlackWebhookSender(env, lambda req, timeout=None: posted.append(req)),
    )
    assert sent == [m.recipient_key for m in messages]
    assert len(FakeSMTP.sent) == len(posted) == len(messages)
    owner_mail = FakeSMTP.sent[0]
    assert [p.get_filename() for p in owner_mail.iter_attachments()] == ["dashboard.html"]
    assert json.loads(posted[0].data)["blocks"]


def test_cli_digest_is_a_dry_run_by_default_and_never_touches_the_network(
    tmp_path, monkeypatch, capsys
):
    def boom(*a, **k):
        raise AssertionError("network or SMTP used during a dry run")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    monkeypatch.setattr("urllib.request.urlopen", boom)
    code = main(["digest", "--out-dir", str(tmp_path / "out"), "--state-dir", str(tmp_path / "st")])
    assert code == 0
    assert "Nothing was sent" in capsys.readouterr().out
    assert (tmp_path / "out" / "default-owner" / "email.txt").exists()
    assert list((tmp_path / "st").glob("snapshot-*.json"))


def test_cli_send_with_the_example_config_is_refused(tmp_path, monkeypatch, capsys):
    for name in (*REAL_ENV, "SPEND_RADAR_SLACK_WEBHOOK"):
        monkeypatch.delenv(name, raising=False)
    code = main(
        ["digest", "--send", "--out-dir", str(tmp_path), "--state-dir", str(tmp_path / "s")]
    )
    assert code == 2
    assert "Nothing was sent" in capsys.readouterr().err
