import base64
import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class PaymentProviderError(Exception):
    pass


def _request_json(url, data=None, headers=None, method=None):
    request = Request(
        url,
        data=data,
        headers=headers or {},
        method=method or ('POST' if data is not None else 'GET'),
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaymentProviderError('The payment provider could not be reached or returned an invalid response.') from exc


def _paypal_base_url():
    if settings.PAYPAL_MODE not in ('sandbox', 'live'):
        raise PaymentProviderError('PayPal mode must be set to sandbox or live.')
    host = 'api-m.sandbox.paypal.com' if settings.PAYPAL_MODE == 'sandbox' else 'api-m.paypal.com'
    return f'https://{host}'


def _paypal_token():
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise PaymentProviderError('PayPal credentials are not configured.')
    credentials = base64.b64encode(
        f'{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}'.encode('utf-8')
    ).decode('ascii')
    response = _request_json(
        f'{_paypal_base_url()}/v1/oauth2/token',
        data=b'grant_type=client_credentials',
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    token = response.get('access_token')
    if not token:
        raise PaymentProviderError('PayPal did not provide an access token.')
    return token


def _paypal_amount(booking):
    try:
        ngn_per_unit = Decimal(settings.PAYPAL_NGN_PER_UNIT)
    except (InvalidOperation, TypeError):
        raise PaymentProviderError('Configure PAYPAL_NGN_PER_UNIT before enabling PayPal.')
    if ngn_per_unit <= 0:
        raise PaymentProviderError('PAYPAL_NGN_PER_UNIT must be greater than zero.')
    amount = (booking.trip.fare_amount / ngn_per_unit).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    return amount


def create_paypal_order(booking, return_url, cancel_url):
    amount = _paypal_amount(booking)
    token = _paypal_token()
    response = _request_json(
        f'{_paypal_base_url()}/v2/checkout/orders',
        data=json.dumps({
            'intent': 'CAPTURE',
            'purchase_units': [{
                'reference_id': str(booking.pk),
                'custom_id': f'APL-{booking.pk}',
                'amount': {
                    'currency_code': settings.PAYPAL_CURRENCY,
                    'value': f'{amount:.2f}',
                },
            }],
            'application_context': {
                'return_url': return_url,
                'cancel_url': cancel_url,
                'user_action': 'PAY_NOW',
            },
        }).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
    )
    approval_url = next(
        (link.get('href') for link in response.get('links', []) if link.get('rel') == 'approve'),
        None,
    )
    if not response.get('id') or not approval_url:
        raise PaymentProviderError('PayPal did not return a checkout approval link.')
    return approval_url


def verify_paypal_return(order_id, booking):
    token = _paypal_token()
    response = _request_json(
        f'{_paypal_base_url()}/v2/checkout/orders/{order_id}/capture',
        data=b'{}',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
    )
    if response.get('status') != 'COMPLETED':
        raise PaymentProviderError('PayPal has not completed this payment.')
    purchase_units = response.get('purchase_units', [])
    expected_amount = f'{_paypal_amount(booking):.2f}'
    for unit in purchase_units:
        captures = unit.get('payments', {}).get('captures', [])
        for capture in captures:
            amount = capture.get('amount', {})
            if (
                unit.get('custom_id') == f'APL-{booking.pk}'
                and capture.get('status') == 'COMPLETED'
                and amount.get('currency_code') == settings.PAYPAL_CURRENCY
                and amount.get('value') == expected_amount
            ):
                return
    raise PaymentProviderError('PayPal payment details did not match this booking.')


def _remita_credentials():
    required = (
        settings.REMITA_MERCHANT_ID,
        settings.REMITA_SERVICE_TYPE_ID,
        settings.REMITA_API_KEY,
    )
    if not all(required):
        raise PaymentProviderError('Remita merchant credentials are not configured.')
    return required


def _find_value(data, key):
    if isinstance(data, dict):
        for current_key, value in data.items():
            if current_key.lower() == key.lower():
                return value
        for value in data.values():
            found = _find_value(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_value(value, key)
            if found is not None:
                return found
    return None


def create_remita_checkout(booking, passenger, return_url):
    merchant_id, service_type_id, api_key = _remita_credentials()
    order_id = f'APL-{booking.pk}'
    amount = f'{booking.trip.fare_amount:.2f}'
    authorization = hashlib.sha512(
        f'{merchant_id}{service_type_id}{order_id}{amount}{api_key}'.encode('utf-8')
    ).hexdigest()
    request_id = f'{booking.pk}-{booking.booking_date.timestamp():.0f}'
    response = _request_json(
        f'{settings.REMITA_BASE_URL.rstrip("/")}/remita/exapp/api/v1/send/api/echannelsvc/merchant/api/paymentinit',
        data=json.dumps({
            'serviceTypeId': service_type_id,
            'amount': amount,
            'orderId': order_id,
            'payerName': passenger.get_full_name(),
            'payerEmail': passenger.email,
            'payerPhone': passenger.phone,
            'description': f'Plateau Poly bus booking {order_id}',
            'responseurl': return_url,
        }).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'MERCHANT_ID': merchant_id,
            'API_KEY': api_key,
            'REQUEST_ID': request_id,
            'AUTHORIZATION': authorization,
        },
    )
    rrr = _find_value(response, 'RRR')
    if not rrr:
        raise PaymentProviderError('Remita did not issue a payment reference.')
    return f'{settings.REMITA_CHECKOUT_URL}?{urlencode({"merchantId": merchant_id, "rrr": rrr})}'


def verify_remita_return(rrr, booking):
    merchant_id, _, api_key = _remita_credentials()
    authorization = hashlib.sha512(f'{merchant_id}{rrr}{api_key}'.encode('utf-8')).hexdigest()
    response = _request_json(
        f'{settings.REMITA_BASE_URL.rstrip("/")}/remita/ecomm/{merchant_id}/{rrr}/{authorization}/status.reg'
    )
    status = str(_find_value(response, 'status') or '').lower()
    response_code = str(_find_value(response, 'responseCode') or '')
    order_id = str(_find_value(response, 'orderId') or '')
    amount = _find_value(response, 'amount')
    if status not in ('payment successful', '00') and response_code != '00':
        raise PaymentProviderError('Remita has not confirmed this payment.')
    if order_id != f'APL-{booking.pk}':
        raise PaymentProviderError('Remita payment does not match this booking.')
    try:
        confirmed_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError):
        raise PaymentProviderError('Remita did not return a valid payment amount.')
    if confirmed_amount != booking.trip.fare_amount:
        raise PaymentProviderError('Remita payment amount does not match this booking.')