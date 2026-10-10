# Payment Provider Setup

The payment page uses hosted PayPal or Remita checkout. A booking is marked paid only after the server verifies the provider's confirmation. Do not store provider credentials in source control.

## Bank Transfer

The payment page also displays these transfer details:

- Bank: UBA
- Account name: Hezekiah Gocheka Rumson
- Account number: 2110968009

Passengers select **Bank Transfer** to open the transfer instructions, then transfer the exact fare shown using their bank app or branch. They do not need to enter a transfer reference in the app. The booking stays pending until a staff member checks the bank account and confirms the transfer in Django Admin under **Payments** (select the pending bank transfer and choose **Confirm selected bank transfers and email receipts**). Confirmation marks the booking paid and emails the passenger the payment receipt/invoice as a PDF attachment, with links to view or download it. The passenger can also download the PDF or print the receipt from the receipt page. The amount is taken from the trip fare when the transfer is submitted and refreshed from the trip fare when staff confirms it.

## Email

In development, Django prints confirmation emails in the runserver console. For production, configure the SMTP environment variables `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` so passenger receipts can be delivered. Email delivery failures are logged and shown to staff; a verified payment remains confirmed.

## PayPal

Create an app in the PayPal developer dashboard and set these environment variables:

```powershell
$env:PAYPAL_CLIENT_ID = "your-client-id"
$env:PAYPAL_CLIENT_SECRET = "your-client-secret"
$env:PAYPAL_MODE = "sandbox"
$env:PAYPAL_CURRENCY = "USD"
$env:PAYPAL_NGN_PER_UNIT = "1500"
```

`PAYPAL_NGN_PER_UNIT` is the current NGN value of one unit of the selected PayPal currency. The school must maintain this rate; the app converts each NGN trip fare using it. Use `PAYPAL_MODE=live` and live PayPal credentials only after completing sandbox tests.

## Remita

Set the merchant credentials supplied by Remita. The defaults use Remita's demo endpoints:

```powershell
$env:REMITA_MERCHANT_ID = "your-merchant-id"
$env:REMITA_SERVICE_TYPE_ID = "your-service-type-id"
$env:REMITA_API_KEY = "your-api-key"
$env:REMITA_BASE_URL = "https://remitademo.net"
$env:REMITA_CHECKOUT_URL = "https://remitademo.net/remita/ecomm/finalize.reg"
```

Use the production base and checkout URLs issued by Remita for live payments. The app sends the passenger's registered name, email, and phone to Remita and verifies the returned RRR against the booking and fare.

## Before Going Live

Run migrations with `python manage.py migrate`, test each provider in its sandbox, and deploy behind HTTPS with the public site URL accepted by the provider. Keep `DEBUG` disabled in production and load merchant secrets from the hosting environment. The app cannot complete real transactions until the institution provisions active merchant credentials.