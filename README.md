# UniOne Django

[![Django](https://img.shields.io/pypi/v/unione-django)](https://pypi.org/project/unione-django/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Django integration of the [UniOne Python SDK](https://github.com/unione-repo/unione-python-sdk) (``): the API client in the settings (`get_client()`), a webhook endpoint with signature check, a Django email transport that sends through `email/send`.

[API reference](https://docs.unione.io/en/web-api-ref) · Docs for LLMs: [llms.txt](https://docs.unione.io/llms.txt)

## Install

```bash
pip install unione-django
```

Requirements: Python 3.8+, Django 4.2+.

## Configuration

Get an API key in the [control panel](https://cp.unione.io/en/settings/security/api) and keep it in the environment, never in code:

```bash
export UNIONE_API_KEY="your-api-key"
```

Settings are read from the environment by default:

```python
# settings.py
INSTALLED_APPS = [..., "unione_wrapper"]

UNIONE = {
    "API_KEY": os.environ["UNIONE_API_KEY"],
    "HOST": "us1.unione.io",  # optional
}
MAILERS = {"default": {"BACKEND": "unione_wrapper.mail.EmailBackend"}}  # Django 6.1+
# EMAIL_BACKEND = "unione_wrapper.mail.EmailBackend"                    # Django < 6.1
DEFAULT_FROM_EMAIL = "Shop <shop@example.com>"

# urls.py
urlpatterns = [..., path("unione/", include("unione_wrapper.urls"))]  # /unione/webhook
```

`us1.unione.io` in the example is for an account on another datacenter; without the host setting the package uses `api.unione.io`.

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `UNIONE["API_KEY"]` | `UNIONE_API_KEY` |  | User or project API key (required). |
| `UNIONE["HOST"]` | `UNIONE_HOST` | `api.unione.io` | API host (datacenter: `api.unione.io`, `eu1.unione.io`, `us1.unione.io`) or a full base URL. |
| `UNIONE["TIMEOUT"]` | `UNIONE_TIMEOUT` | `30` | Request timeout, seconds. |
| `UNIONE["WEBHOOK_KEY"]` | `UNIONE_WEBHOOK_KEY` |  | API key the webhooks are signed with (the key of the user/project of the webhook), if it differs from the API key. |

Settings of the `UNIONE` dict win over the environment variables. The webhook URL is set by `include("unione_wrapper.urls")`; the view is `csrf_exempt`.

## Sending mail

Messages of the Django email go through [email/send](https://docs.unione.io/en/web-api-ref#email-send): from, to/cc/bcc, reply-to, subject, HTML and text parts, attachments, inline images and `X-*` headers.

```python
from django.core.mail import EmailMultiAlternatives, send_mail

send_mail("Order shipped", "Your order is on its way", None, ["user@example.com"])

message = EmailMultiAlternatives("Order shipped", "Text", to=["User <user@example.com>"], headers={"X-Order": "42"})
message.attach_alternative("<b>HTML</b>", "text/html")
message.tags = ["orders"]                 # -> tags
message.metadata = {"order_id": "42"}     # -> global_metadata
message.send()
print(message.job_id)
```

No verified domain yet? Send from the [test sandbox domain](#no-domain-yet-the-test-sandbox-domain).

## Webhooks

The endpoint answers `GET` with 200 OK (the URL check of [webhook/set](https://docs.unione.io/en/web-api-ref#webhook-set)) and accepts the `POST` notifications: it checks the `auth` field (MD5 of the request body in which the `auth` value is replaced by the API key), answers 401 to a wrong signature, and passes the notification and each of its events to the application.

```python
from django.dispatch import receiver
from unione_wrapper.signals import webhook_event_received


@receiver(webhook_event_received)
def on_event(sender, event, user, **kwargs):
    data = event.event_data
    print(event.event_name, data.email, data.status)
```

Register the URL of the endpoint with `webhook/set`, e.g. `https://example.com/unione/webhook`.

> **Answer 200 within 3 seconds** and process the events in the background (a queue): otherwise UniOne repeats the request every 10 minutes for 24 hours (`retry_count` grows), and a handler that failed every request for at least 10 events of a day is turned inactive. The handler must take at least **5 parallel requests of up to 100 events each**; deduplicate, a repeat delivers the same events again.

## API client

Every section of the API is available on the client, see the [SDK docs](https://github.com/unione-repo/unione-python-sdk).

```python
from unione_wrapper import get_client

info = get_client().system.info()
print(info.accounting)
```

### Sending through the API

Besides the Django email, mail can be sent through the API client directly. The client calls [email/send](https://docs.unione.io/en/web-api-ref#email-send) with all of its options: templates, substitutions, metadata, tracking. Fields of the request and other examples: [Python SDK docs](https://github.com/unione-repo/unione-python-sdk/blob/HEAD/docs/Email.md#send).

```python
from django.http import JsonResponse
from unione.api.email import EmailSendRequest, MessageObject, MessageObjectRecipientsItem as Recipient
from unione.common import BodyObject
from unione_wrapper import get_client


def send_email(request):
    client = get_client()
    response = client.email.send(EmailSendRequest(
        message=MessageObject(
            recipients=[Recipient.from_address("Alex <alex@example.com>")],
            from_email="shop@example.com",
            from_name="Shop",
            subject="Your order",
            body=BodyObject.from_html("<p>Hello, {{to_name}}! Your order has shipped.</p>"),
        ),
    ))
    return JsonResponse({"job_id": response.job_id})
```

## No domain yet: the test sandbox domain

Until your domain is verified, send from the **sandbox domain**: a test domain every account has, already verified, with DKIM and SPF set. It delivers only to addresses you confirm (the confirmation link comes by email, valid 48 hours), up to 100 emails a day. The sandbox domain is deleted 31 days after it was created, but you can get it again: the next `domain/get-sandbox-domain` call creates a new one (with a new name, so read it from the call, do not hardcode it).

The examples use the API client of the package (see the configuration above).

```python
from django.http import JsonResponse
from unione.api.confirmed_email import ConfirmedEmailRequest
from unione.api.email import EmailSendRequest, MessageObject, MessageObjectRecipientsItem as Recipient
from unione.common import BodyObject
from unione_wrapper import get_client


def send_from_sandbox(request):
    client = get_client()

    # 1. Your sandbox domain: created on the first call, the same one afterwards
    domain = client.domain.get_sandbox_domain().domain

    # 2. Confirm your inbox: UniOne sends a link, click it within 48 hours
    client.confirmed_email.create(ConfirmedEmailRequest(email="you@example.com"))

    # 3. Send from any address on the sandbox domain to the confirmed one
    client.email.send(EmailSendRequest(
        message=MessageObject(
            recipients=[Recipient.from_address("you@example.com")],
            from_email=f"noreply@{domain}",
            subject="Hello from UniOne",
            body=BodyObject.from_html("<p>It works!</p>"),
        ),
    ))

    return JsonResponse({"domain": domain})
```

<details>
<summary>Sandbox limits</summary>

- Sends only to confirmed addresses: up to 10 per account.
- Up to 100 emails a day.
- The sandbox domain expires after 31 days; call `domain/get-sandbox-domain` again to get a new one.
- Works only with the account API key, not a project key.
- Not listed in `domain/list`; the other `domain/*` methods do not apply to it.

The sandbox is for development and testing. Do not use a sandbox domain as the sender in production.

</details>

<details>
<summary>The same with curl</summary>

```bash
BASE=https://api.unione.io/en/transactional/api/v1

curl -s -X POST $BASE/domain/get-sandbox-domain.json \
  -H "Content-Type: application/json" -H "X-API-KEY: $UNIONE_API_KEY" -d '{}'

curl -s -X POST $BASE/confirmed-email/create.json \
  -H "Content-Type: application/json" -H "X-API-KEY: $UNIONE_API_KEY" \
  -d '{"email": "you@example.com"}'

curl -s -X POST $BASE/email/send.json \
  -H "Content-Type: application/json" -H "X-API-KEY: $UNIONE_API_KEY" \
  -d '{
        "message": {
          "recipients": [
            {
              "email": "you@example.com"
            }
          ],
          "from_email": "noreply@<sandbox-domain>",
          "subject": "Hello from UniOne",
          "body": {
            "html": "<p>It works!</p>"
          }
        }
      }'
```

</details>

## Going to production

**1. Verify your sending domain.** `domain/get-dns-records` returns the verification record, the DKIM key and the DMARC target; add the records at your DNS provider, then `domain/validate-verification-record` and `domain/validate-dkim`.

| Type | Host | Value | Where it comes from |
|---|---|---|---|
| TXT | `@` | `unione-validate-hash=…` | `verification-record` of the response, as is |
| TXT | `<selector>._domainkey` (the selector is on the domain page of the control panel, e.g. `us`) | `v=DKIM1; k=rsa; p=<dkim>` | `dkim` of the response after `v=DKIM1; k=rsa; p=` |
| TXT | `@` | `v=spf1 include:spf.unione.io ~all` | not in the response; add the include to your SPF record if you have one |
| CNAME | `_dmarc` | `<domain>.dmarc.…` | `dmarc` of the response (UniOne publishes the DMARC policy); keep your own DMARC TXT record instead if the domain has one |

**2. Make sending reliable.**

| | |
|---|---|
| Retries | `429` and `5xx` with backoff and the same `idempotence_key`; fix other errors instead of retrying |
| Limits | 500 recipients and 10 MB per request, attachments included: base64 makes a file about a third larger |
| Body | always `html` or `plaintext` (a template can supply it) |
| Delivery status | a webhook, not polling |
| Queue | send from a background job, not inside the web request |
| Config | `from_email` from config, so the sandbox → production switch needs no code change |
| Defaults | keep the unsubscribe footer and tracking; changing them needs UniOne support |

## Help

- [Integration guides](https://docs.unione.io/en/integrations)
- [Python SDK](https://github.com/unione-repo/unione-python-sdk)
- AI coding agents: [llms.txt](https://docs.unione.io/llms.txt), the [MCP server](https://unione.io/en/agents), skills: `npx skills add https://github.com/unione-repo/unione-skills.git`
- [Support](https://cp.unione.io/en/support) · [Issues](https://github.com/unione-repo/unione-django/issues)
- Contributing: [AGENTS.md](AGENTS.md) — the package is generated from the OpenAPI spec.
