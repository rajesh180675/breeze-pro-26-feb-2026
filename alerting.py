"""External alert dispatch for Breeze PRO."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import queue
import smtplib
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any, Dict, List, Tuple

import requests

log = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class AlertEvent:
    alert_type: str
    level: AlertLevel
    title: str
    body: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AlertConfig:
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    email_enabled: bool = False
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_to: str = ""

    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_secret: str = ""
    discord_enabled: bool = False
    discord_webhook_url: str = ""

    whatsapp_enabled: bool = False
    whatsapp_to: str = ""
    whatsapp_from: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    alert_template: str = "{level} {title}\n{body}"

    alert_on_fill: bool = True
    alert_on_stop_loss: bool = True
    alert_on_gtt_trigger: bool = True
    alert_on_margin_warning: bool = True
    alert_on_errors: bool = False


class TelegramDispatcher:
    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"
    MAX_MESSAGE_LEN = 4096

    def __init__(self, bot_token: str, chat_id: str, timeout: int = 10):
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self._token or not self._chat_id:
            return False
        url = self.BASE_URL.format(token=self._token)
        if len(text) > self.MAX_MESSAGE_LEN:
            text = text[: self.MAX_MESSAGE_LEN - 3] + "..."
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
            ok = bool(resp.json().get("ok", False))
            if not ok:
                log.warning("Telegram send failed: %s", resp.text[:200])
            return ok
        except Exception as e:
            log.error("Telegram dispatch error: %s", e)
            return False

    def format_alert(self, event: AlertEvent) -> str:
        level_emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(event.level.value, "📢")
        lines = [
            f"{level_emoji} <b>{event.title}</b>",
            f"<i>{event.timestamp[:19]}</i>",
            "",
            event.body,
        ]
        for k, v in event.metadata.items():
            lines.append(f"• <b>{k}:</b> {v}")
        return "\n".join(lines)


class EmailDispatcher:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        to_address: str,
        from_name: str = "Breeze PRO Alerts",
        timeout: int = 15,
    ):
        self._host = smtp_host
        self._port = smtp_port
        self._user = username
        self._pass = password
        self._to = to_address
        self._from_name = from_name
        self._timeout = timeout

    def send(self, subject: str, html_body: str) -> bool:
        if not all([self._host, self._user, self._pass, self._to]):
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self._from_name} <{self._user}>"
            msg["To"] = self._to
            msg.attach(MIMEText(html_body, "html"))

            context = ssl.create_default_context()
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(self._user, self._pass)
                server.send_message(msg)
            return True
        except Exception as e:
            log.error("Email dispatch error: %s", e)
            return False

    def format_alert(self, event: AlertEvent) -> Tuple[str, str]:
        level_key = event.level.value
        level_color = {"INFO": "#0d6efd", "WARNING": "#fd7e14", "CRITICAL": "#dc3545"}.get(level_key, "#6c757d")
        metadata_rows = "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in event.metadata.items())

        html = f"""
        <html><body style="font-family:Arial,sans-serif;max-width:600px">
          <div style="background:{level_color};color:white;padding:1rem;border-radius:6px 6px 0 0">
            <h2 style="margin:0">{event.title}</h2>
            <small>{event.timestamp[:19]}</small>
          </div>
          <div style="padding:1rem;border:1px solid #dee2e6;border-radius:0 0 6px 6px">
            <p>{event.body}</p>
            {"<table>" + metadata_rows + "</table>" if metadata_rows else ""}
          </div>
        </body></html>
        """
        return f"[Breeze PRO {level_key}] {event.title}", html


class WebhookDispatcher:
    def __init__(self, url: str, secret: str = "", timeout: int = 10):
        self._url = url
        self._secret = secret
        self._timeout = timeout

    def build_payload(self, event: AlertEvent) -> Dict[str, Any]:
        return {
            "alert_type": event.alert_type,
            "level": event.level.value,
            "title": event.title,
            "body": event.body,
            "metadata": event.metadata,
            "timestamp": event.timestamp,
        }

    def _serialize_payload(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def signature_for_payload(self, payload: Dict[str, Any]) -> str:
        if not self._secret:
            return ""
        return hmac.new(self._secret.encode(), self._serialize_payload(payload).encode(), hashlib.sha256).hexdigest()

    def verify_signature(self, raw_body: str, provided_signature: str) -> bool:
        """Verify incoming webhook signature using HMAC-SHA256."""
        if not self._secret:
            return False
        expected = hmac.new(self._secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, provided_signature or "")

    def send(self, event: AlertEvent) -> bool:
        if not self._url:
            return False
        try:
            payload = self.build_payload(event)
            body = self._serialize_payload(payload)
            headers = {"Content-Type": "application/json"}
            if self._secret:
                headers["X-Signature"] = self.signature_for_payload(payload)
            resp = requests.post(self._url, data=body, headers=headers, timeout=self._timeout)
            return resp.status_code < 300
        except Exception as e:
            log.error("Webhook dispatch error: %s", e)
            return False


class DiscordDispatcher:
    def __init__(self, webhook_url: str, timeout: int = 10):
        self._webhook_url = webhook_url
        self._timeout = timeout

    def send(self, event: AlertEvent) -> bool:
        if not self._webhook_url:
            return False
        payload = {
            "content": f"**{event.level.value}** {event.title}\n{event.body}",
        }
        try:
            resp = requests.post(self._webhook_url, json=payload, timeout=self._timeout)
            return resp.status_code < 300
        except Exception as exc:
            log.error("Discord dispatch error: %s", exc)
            return False


class WhatsAppDispatcher:
    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str, timeout: int = 10):
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._to = to_number
        self._timeout = timeout

    def send(self, text: str) -> bool:
        if not all([self._sid, self._token, self._from, self._to]):
            return False
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        data = {"From": self._from, "To": self._to, "Body": text}
        try:
            resp = requests.post(url, data=data, auth=(self._sid, self._token), timeout=self._timeout)
            return resp.status_code < 300
        except Exception as exc:
            log.error("WhatsApp dispatch error: %s", exc)
            return False


class AlertDispatcher:
    MAX_HISTORY = 500

    def __init__(self, config: AlertConfig):
        self._config = config
        self._history: List[Dict] = []
        self._lock = threading.Lock()
        self._dedupe_window_seconds = 300
        self._dedupe_cache: Dict[str, float] = {}
        self._queue: "queue.Queue[AlertEvent]" = queue.Queue(maxsize=1000)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="AlertDispatchWorker")
        self._worker.start()
        self._rebuild_dispatchers()

    def update_config(self, config: AlertConfig) -> None:
        self._config = config
        self._rebuild_dispatchers()

    def _rebuild_dispatchers(self) -> None:
        cfg = self._config
        self._telegram = TelegramDispatcher(cfg.telegram_bot_token, cfg.telegram_chat_id) if cfg.telegram_enabled else None
        self._email = EmailDispatcher(cfg.email_smtp_host, cfg.email_smtp_port, cfg.email_username, cfg.email_password, cfg.email_to) if cfg.email_enabled else None
        self._webhook = WebhookDispatcher(cfg.webhook_url, cfg.webhook_secret) if cfg.webhook_enabled else None
        self._discord = DiscordDispatcher(cfg.discord_webhook_url) if cfg.discord_enabled else None
        self._whatsapp = WhatsAppDispatcher(
            cfg.twilio_account_sid,
            cfg.twilio_auth_token,
            cfg.whatsapp_from,
            cfg.whatsapp_to,
        ) if cfg.whatsapp_enabled else None

    def _render_template(self, event: AlertEvent) -> str:
        context = {
            "alert_type": event.alert_type,
            "level": event.level.value,
            "title": event.title,
            "body": event.body,
            "timestamp": event.timestamp,
            **{str(k): str(v) for k, v in event.metadata.items()},
        }
        text = self._config.alert_template or "{level} {title}\n{body}"
        for k, v in context.items():
            text = text.replace("{" + k + "}", str(v))
        return text

    def _event_key(self, event: AlertEvent) -> str:
        blob = json.dumps(
            {
                "alert_type": event.alert_type,
                "level": event.level.value,
                "title": event.title,
                "body": event.body,
                "metadata": event.metadata,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def dispatch(self, event: AlertEvent) -> None:
        """Non-blocking dispatch. Duplicate events within 5 minutes are dropped."""
        now = time.time()
        key = self._event_key(event)
        with self._lock:
            self._dedupe_cache = {k: t for k, t in self._dedupe_cache.items() if now - t < self._dedupe_window_seconds}
            if key in self._dedupe_cache:
                return
            self._dedupe_cache[key] = now

        try:
            self._queue.put_nowait(event)
        except queue.Full:
            log.warning("Alert queue full; dropping event: %s", event.title)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._send_all(event)
            finally:
                self._queue.task_done()

    def _send_all(self, event: AlertEvent) -> None:
        rendered = self._render_template(event)
        channels: List[str] = []
        if self._telegram:
            if self._telegram.send(rendered):
                channels.append("telegram")
        if self._email:
            subject, html = self._email.format_alert(event)
            if self._email.send(subject, html):
                channels.append("email")
        if self._webhook:
            if self._webhook.send(event):
                channels.append("webhook")
        if self._discord:
            if self._discord.send(event):
                channels.append("discord")
        if self._whatsapp:
            if self._whatsapp.send(rendered):
                channels.append("whatsapp")
        with self._lock:
            self._history.append(
                {
                    "type": event.alert_type,
                    "level": event.level.value,
                    "title": event.title,
                    "timestamp": event.timestamp,
                    "channels": ",".join(channels) if channels else "none",
                }
            )
            if len(self._history) > self.MAX_HISTORY:
                self._history = self._history[-self.MAX_HISTORY :]

    def get_history(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return list(reversed(self._history[-limit:]))

    def test_telegram(self) -> bool:
        return bool(self._telegram and self._telegram.send("✅ Breeze PRO: Telegram alerts are working correctly."))

    def test_email(self) -> bool:
        return bool(self._email and self._email.send("[Breeze PRO] Alert Test", "<p>✅ Email alerts are configured correctly.</p>"))


def create_fill_alert(stock_code: str, exchange: str, action: str, quantity: int, price: float, order_id: str) -> AlertEvent:
    return AlertEvent(
        alert_type="TRADE_FILLED",
        level=AlertLevel.INFO,
        title=f"Order Filled: {action.upper()} {stock_code}",
        body=f"{action.upper()} {quantity} × {stock_code} @ ₹{price:.2f}",
        metadata={
            "Order ID": order_id,
            "Exchange": exchange,
            "Price": f"₹{price:.2f}",
            "Quantity": str(quantity),
            "Value": f"₹{price * quantity:,.0f}",
        },
    )


def create_stop_loss_alert(stock_code: str, strike: int, right: str, ltp: float, stop_price: float, loss: float) -> AlertEvent:
    formatted_body = (
        f"🚨 STOP LOSS HIT — {stock_code} {strike} {right.upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Position: SELL 1 lot\n"
        f"⚡ Current: ₹{ltp:.2f}\n"
        f"💥 Loss: ₹{loss:,.0f}\n"
        f"⏰ Time: {datetime.now().strftime('%H:%M:%S')} IST\n"
        f"🎯 Action: AUTO-SQUARE OFF triggered\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"[View Position] [Dismiss]"
    )
    return AlertEvent(
        alert_type="STOP_LOSS_HIT",
        level=AlertLevel.CRITICAL,
        title=f"🚨 STOP LOSS HIT — {stock_code} {strike} {right.upper()}",
        body=formatted_body,
        metadata={
            "Instrument": f"{stock_code} {strike} {right.upper()}",
            "LTP": f"₹{ltp:.2f}",
            "Stop Price": f"₹{stop_price:.2f}",
            "Estimated Loss": f"₹{loss:,.0f}",
        },
    )


def create_margin_warning_alert(available: float, required: float) -> AlertEvent:
    utilization = (1 - available / max(required, 1)) * 100
    return AlertEvent(
        alert_type="MARGIN_CALL",
        level=AlertLevel.CRITICAL,
        title="⚠️ Low Margin Warning",
        body=f"Available margin ₹{available:,.0f} is critically low. Margin utilization: {utilization:.1f}%",
        metadata={
            "Available Margin": f"₹{available:,.0f}",
            "Utilization": f"{utilization:.1f}%",
        },
    )
