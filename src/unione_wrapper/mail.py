"""Django email backend: EMAIL_BACKEND = "unione_wrapper.mail.EmailBackend".

EmailMessage / EmailMultiAlternatives -> email/send: from, to/cc/bcc (the display name goes to the "to_name"
substitution), reply_to, subject, text and HTML parts, attachments (MIMEBase parts with a Content-ID and an inline
disposition become inline_attachments), X-* and List-* / In-Reply-To / References headers.
Extra attributes of a message: tags (list of str) -> tags, metadata (dict) -> global_metadata.
After sending, message.job_id holds the job_id of the API.
"""
from __future__ import annotations

import base64
import mimetypes
from email.mime.base import MIMEBase
from email.utils import formataddr, getaddresses, parseaddr
from typing import Any, Dict, List, Optional

from django.conf import settings as django_settings
from django.core.mail.backends.base import BaseEmailBackend

from unione.client import ApiError

PASSED_HEADERS = ('list-unsubscribe', 'list-subscribe', 'list-help', 'list-owner', 'list-archive', 'in-reply-to', 'references')


def _addresses(values) -> List[tuple]:
    return [(name, email) for name, email in getaddresses([str(v) for v in values or []]) if email]


def _attachment(item) -> tuple:
    """(inline, {type, name, content}) of an attachment of EmailMessage.attachments."""
    if isinstance(item, MIMEBase):
        content = item.get_payload(decode=True) or b""
        cid = (item.get("Content-ID") or "").strip("<> ")
        inline = bool(cid) and str(item.get("Content-Disposition") or "").startswith("inline")
        name = cid if inline else (item.get_filename() or cid or "attachment")
        return inline, {"type": item.get_content_type(), "name": name,
                        "content": base64.b64encode(content).decode("ascii")}
    filename, content, mimetype = item[0], item[1], item[2] if len(item) > 2 else None
    if isinstance(content, str):
        content = content.encode("utf-8")
    mimetype = mimetype or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    return False, {"type": mimetype, "name": filename or "attachment",
                   "content": base64.b64encode(content).decode("ascii")}


def message_payload(message) -> Dict[str, Any]:
    """The "message" of email/send for a Django EmailMessage."""
    from_name, from_email = parseaddr(str(message.from_email or django_settings.DEFAULT_FROM_EMAIL))
    to, cc, bcc = _addresses(message.to), _addresses(message.cc), _addresses(message.bcc)
    recipients = []
    for name, email in to + cc + bcc:
        recipient: Dict[str, Any] = {"email": email}
        if name:
            recipient["substitutions"] = {"to_name": name}
        recipients.append(recipient)
    payload: Dict[str, Any] = {"recipients": recipients, "subject": str(message.subject or ""),
                               "from_email": from_email}
    if from_name:
        payload["from_name"] = from_name
    reply_to = _addresses(message.reply_to)
    if reply_to:
        payload["reply_to"] = reply_to[0][1]
        if reply_to[0][0]:
            payload["reply_to_name"] = reply_to[0][0]

    body: Dict[str, str] = {}
    if message.body:
        body["html" if getattr(message, "content_subtype", "plain") == "html" else "plaintext"] = str(message.body)
    for alternative in getattr(message, "alternatives", None) or []:
        content, mimetype = alternative[0], alternative[1]
        if mimetype == "text/html":
            body["html"] = content.decode("utf-8") if isinstance(content, bytes) else str(content)
    if body:
        payload["body"] = body

    headers: Dict[str, str] = {}
    if cc:
        headers["To"] = ", ".join(formataddr(a) for a in to)
        headers["CC"] = ", ".join(formataddr(a) for a in cc)
    for name, value in (message.extra_headers or {}).items():
        if name.lower().startswith("x-") or name.lower() in PASSED_HEADERS:
            headers[name] = str(value)
    if headers:
        payload["headers"] = headers

    for item in message.attachments or []:
        inline, data = _attachment(item)
        payload.setdefault("inline_attachments" if inline else "attachments", []).append(data)
    tags = getattr(message, "tags", None)
    if tags:
        payload["tags"] = [str(tag) for tag in tags]
    metadata = getattr(message, "metadata", None)
    if metadata:
        payload["global_metadata"] = {str(k): str(v) for k, v in metadata.items()}
    return payload


class EmailBackend(BaseEmailBackend):
    """Sends the messages through email/send of the UniOne API.

    Options (OPTIONS of a MAILERS entry, Django 6.1+, or get_connection() kwargs): api_key, host, timeout - default:
    the client of the project settings.
    """

    def __init__(self, fail_silently: bool = False, *, api_key: Optional[str] = None, host: Optional[str] = None,
                 timeout: Optional[float] = None, api_client=None, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # alias (MAILERS) and the unknown options are checked by Django
        self.fail_silently = fail_silently
        self._api_client = api_client
        self._options = {"api_key": api_key, "host": host, "timeout": timeout}

    @property
    def api_client(self):
        if self._api_client is None:
            from . import api_client_for, get_api_client

            options = {k: v for k, v in self._options.items() if v is not None}
            self._api_client = api_client_for(options) if options else get_api_client()
        return self._api_client

    def send_messages(self, email_messages) -> int:
        sent = 0
        for message in email_messages or []:
            if not message.recipients():
                continue
            try:
                response = self.api_client.call("/email/send.json", {"message": message_payload(message)})
            except (ApiError, ValueError):
                if not self.fail_silently:
                    raise
                continue
            message.job_id = response.get("job_id")
            sent += 1
        return sent
