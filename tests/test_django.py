"""Tests of the Django app: settings, email backend, webhook view, system checks. No network: the HTTP layer of
the SDK is faked (fake_api.py).

    pip install -e ".[test]" && python -m unittest discover -s tests -v
"""
import unittest

import django
from django.conf import settings

from fake_api import (
    API_ERROR,
    API_KEY,
    BASE_PATH,
    BASE_URL,
    KEY_HEADER,
    PLATFORM,
    SEND_PATH,
    WEBHOOK_PATH,
    FakeApi,
    clean_env,
    signed,
)

if django.VERSION >= (6, 1):
    MAIL_SETTINGS = {"MAILERS": {"default": {"BACKEND": "unione_wrapper.mail.EmailBackend"}}}
else:
    MAIL_SETTINGS = {"EMAIL_BACKEND": "unione_wrapper.mail.EmailBackend"}

if not settings.configured:
    settings.configure(
        DEBUG=False,
        ALLOWED_HOSTS=["*"],
        SECRET_KEY="test",
        ROOT_URLCONF="urls_webhook",
        INSTALLED_APPS=["unione_wrapper"],
        **MAIL_SETTINGS,
        DEFAULT_FROM_EMAIL="Shop <shop@example.com>",
        UNIONE={"API_KEY": API_KEY, "HOST": BASE_URL},
        USE_TZ=True,
    )
    django.setup()

from django.core.checks import run_checks  # noqa: E402
from django.core.mail import EmailMultiAlternatives, send_mail  # noqa: E402
from django.test import Client, SimpleTestCase, override_settings  # noqa: E402

from unione.client import ApiError  # noqa: E402
from unione_wrapper import get_client, reset  # noqa: E402
from unione_wrapper.mail import EmailBackend  # noqa: E402
from unione_wrapper.signals import webhook_event_received, webhook_received  # noqa: E402
from unione_wrapper.webhook import WebhookCallback  # noqa: E402

CONFIG = {"API_KEY": API_KEY, "HOST": BASE_URL}


class Base(SimpleTestCase):
    def setUp(self):
        clean_env(self)
        reset()
        self.addCleanup(reset)
        self.api = FakeApi(self)


class ClientTest(Base):
    def test_client_from_settings(self):
        client = get_client()
        self.assertIs(client, get_client())
        self.assertEqual(client.api_client.config.base_url, BASE_URL)
        client.system.ping()
        call = self.api.only_call()
        self.assertEqual(call.path, BASE_PATH + "/system/ping.json")
        self.assertEqual(call.headers[KEY_HEADER], API_KEY)
        self.assertEqual(call.platform, PLATFORM)

    def test_settings_change_resets_the_client(self):
        first = get_client()
        with override_settings(UNIONE={**CONFIG, "API_KEY": "other-key"}):
            self.assertEqual(get_client().api_client.config.api_key, "other-key")
        self.assertIsNot(get_client(), first)

    def test_missing_key(self):
        with override_settings(UNIONE={"HOST": BASE_URL}):
            with self.assertRaises(RuntimeError):
                get_client()


class MailTest(Base):
    def test_message(self):
        message = EmailMultiAlternatives("Test", "Hello", to=["User <user@example.com>"], cc=["cc@example.com"],
                                         headers={"X-Order": "42"}, connection=EmailBackend())
        message.attach_alternative("<b>Hello</b>", "text/html")
        message.attach("a.txt", "abc", "text/plain")
        self.assertEqual(message.send(), 1)
        self.assertEqual(message.job_id, "1ZymBc-00041N-9X")
        call = self.api.only_call()
        self.assertEqual(call.path, BASE_PATH + SEND_PATH)
        self.assertEqual(call.platform, PLATFORM)
        sent = call.body["message"]
        self.assertEqual((sent["from_email"], sent["from_name"], sent["subject"]), ("shop@example.com", "Shop", "Test"))
        self.assertEqual(sent["recipients"], [{"email": "user@example.com", "substitutions": {"to_name": "User"}},
                                              {"email": "cc@example.com"}])
        self.assertEqual(sent["body"], {"plaintext": "Hello", "html": "<b>Hello</b>"})
        self.assertEqual(sent["headers"]["X-Order"], "42")
        self.assertEqual(sent["headers"]["CC"], "cc@example.com")
        self.assertEqual(sent["attachments"], [{"type": "text/plain", "name": "a.txt", "content": "YWJj"}])

    def test_send_mail_uses_the_backend(self):
        self.assertEqual(send_mail("Test", "Hello", None, ["user@example.com"]), 1)
        self.assertEqual(self.api.only_call().body["message"]["recipients"], [{"email": "user@example.com"}])

    def test_api_error(self):
        self.api.reply(SEND_PATH, 400, API_ERROR)
        message = EmailMultiAlternatives("Test", "Hello", to=["user@example.com"], connection=EmailBackend())
        with self.assertRaises(ApiError) as caught:
            message.send()
        self.assertEqual((caught.exception.error_code, caught.exception.http_status), (204, 400))
        self.assertFalse(caught.exception.retryable)
        quiet = EmailMultiAlternatives("Test", "Hello", to=["user@example.com"],
                                       connection=EmailBackend(fail_silently=True))
        self.assertEqual(quiet.send(), 0)

    def test_backend_options(self):
        backend = EmailBackend(api_key="backend-key", host=BASE_URL)
        EmailMultiAlternatives("Test", "Hello", to=["user@example.com"], connection=backend).send()
        self.assertEqual(self.api.only_call().headers[KEY_HEADER], "backend-key")


class WebhookTest(Base):
    def receive(self):
        received = []

        def on_notification(sender, **kwargs):
            received.append(kwargs)

        for signal in (webhook_received, webhook_event_received):
            signal.connect(on_notification)
            self.addCleanup(signal.disconnect, on_notification)
        return received

    def post(self, body):
        return Client().post(WEBHOOK_PATH, data=body, content_type="application/json")

    def test_get(self):
        self.assertEqual(Client().get(WEBHOOK_PATH).status_code, 200)

    def test_signed_post(self):
        received = self.receive()
        response = self.post(signed())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(received), 3)
        self.assertIsInstance(received[0]["callback"], WebhookCallback)
        self.assertEqual(received[1]["event"].event_data.email, "user@example.com")
        self.assertEqual(self.api.calls, [])

    def test_wrong_signature(self):
        received = self.receive()
        body = signed().replace(b"user@", b"evil@")
        self.assertEqual(self.post(body).status_code, 401)
        self.assertEqual(received, [])

    def test_webhook_key(self):
        with override_settings(UNIONE={**CONFIG, "WEBHOOK_KEY": "hook-key"}):
            self.assertEqual(self.post(signed("hook-key")).status_code, 200)
            self.assertEqual(self.post(signed()).status_code, 401)


class ChecksTest(Base):
    def ids(self):
        messages = run_checks(include_deployment_checks=False)
        return sorted(m.id for m in messages if m.id.startswith("unione_wrapper."))

    def test_configured(self):
        self.assertEqual(self.ids(), [])

    def test_no_key_and_no_url(self):
        with override_settings(UNIONE={"API_KEY": ""}, ROOT_URLCONF="urls_empty"):
            self.assertEqual(self.ids(), ["unione_wrapper.W001", "unione_wrapper.W002"])

    def test_webhook_disabled(self):
        with override_settings(UNIONE={**CONFIG, "WEBHOOK_ENABLED": False}, ROOT_URLCONF="urls_empty"):
            self.assertEqual(self.ids(), [])

    def test_view_without_include(self):
        with override_settings(UNIONE=CONFIG, ROOT_URLCONF="urls_plain"):
            self.assertEqual(self.ids(), [])


if __name__ == "__main__":
    unittest.main()
