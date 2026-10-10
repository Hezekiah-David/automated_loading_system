from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Sum
from django.db import transaction
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from django.utils.html import strip_tags
import logging
import smtplib
from .models import Trip, Booking, Passenger, Bus, Route, Payment
from .forms import PassengerRegistrationForm, BookingForm, PaymentForm
from .payments import (
    PaymentProviderError,
    create_paypal_order,
    create_remita_checkout,
    verify_paypal_return,
    verify_remita_return,
)
from .receipts import create_receipt_pdf

logger = logging.getLogger(__name__)

def home(request):
    upcoming_trips = Trip.objects.filter(status='Scheduled').order_by('departure_time')[:5]
    context = {'upcoming_trips': upcoming_trips}
    if request.user.is_staff:
        context.update(_report_context())
    return render(request, 'home.html', context)

def register(request):
    if request.method == 'POST':
        form = PassengerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Registration successful. Welcome!")
            return redirect('passenger_loading:dashboard')
    else:
        form = PassengerRegistrationForm()
    return render(request, 'register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('passenger_loading:dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('passenger_loading:home')

@login_required
def dashboard(request):
    bookings = Booking.objects.filter(passenger=request.user).select_related('trip', 'trip__route')
    return render(request, 'dashboard.html', {'bookings': bookings})

@login_required
def trips(request):
    available_trips = Trip.objects.filter(status='Scheduled').order_by('departure_time')
    return render(request, 'trips.html', {'trips': available_trips})

@login_required
def book_seat(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id, status='Scheduled')
    if trip.is_full():
        messages.error(request, "This trip is fully booked.")
        return redirect('passenger_loading:trips')

    if request.method == 'POST':
        form = BookingForm(request.POST, trip=trip)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.trip = trip
            booking.passenger = request.user
            booking.payment_status = 'Pending'
            try:
                booking.full_clean()  # Validate the model
                booking.save()
                messages.success(request, 'Seat selected. Complete payment to confirm your booking.')
                return redirect('passenger_loading:payment', booking_id=booking.id)
            except Exception as e:
                messages.error(request, f"Error booking seat: {str(e)}")
    else:
        form = BookingForm(trip=trip)

    occupied_seats = set(
        Booking.objects.filter(trip=trip).values_list('seat_number', flat=True)
    )
    return render(request, 'book_seat.html', {
        'trip': trip,
        'form': form,
        'occupied_seats': occupied_seats,
        'seat_numbers': range(1, trip.bus.capacity + 1),
    })

@login_required
def my_bookings(request):
    bookings = Booking.objects.filter(passenger=request.user).order_by('-booking_date')
    return render(request, 'my_bookings.html', {'bookings': bookings})

@login_required
def payment(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('trip', 'trip__route'),
        id=booking_id,
        passenger=request.user,
    )
    if booking.payment_status == 'Paid':
        return redirect('passenger_loading:receipt', booking_id=booking.id)

    provider = request.GET.get('provider')
    try:
        if provider == 'paypal' and request.GET.get('token'):
            verify_paypal_return(request.GET['token'], booking)
            email_sent = confirm_payment(
                booking,
                'PayPal',
                request.build_absolute_uri(reverse('passenger_loading:receipt', args=[booking.id])),
                request.build_absolute_uri(reverse('passenger_loading:receipt_pdf', args=[booking.id])),
            )
            if not email_sent:
                messages.warning(request, 'Payment was confirmed, but the receipt email could not be sent. Please contact the school office.')
            messages.success(request, f'Payment received. Booking confirmed for {booking.passenger.get_full_name() or booking.passenger.username}.')
            return redirect('passenger_loading:receipt', booking_id=booking.id)
        if provider == 'remita' and (request.GET.get('rrr') or request.GET.get('RRR')):
            verify_remita_return(request.GET.get('rrr') or request.GET['RRR'], booking)
            email_sent = confirm_payment(
                booking,
                'Remita',
                request.build_absolute_uri(reverse('passenger_loading:receipt', args=[booking.id])),
                request.build_absolute_uri(reverse('passenger_loading:receipt_pdf', args=[booking.id])),
            )
            if not email_sent:
                messages.warning(request, 'Payment was confirmed, but the receipt email could not be sent. Please contact the school office.')
            messages.success(request, f'Payment received. Booking confirmed for {booking.passenger.get_full_name() or booking.passenger.username}.')
            return redirect('passenger_loading:receipt', booking_id=booking.id)
    except PaymentProviderError as exc:
        messages.error(request, str(exc))

    if request.GET.get('cancelled') == '1':
        messages.info(request, 'Payment was cancelled. Your seat is not confirmed yet.')

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data['method']
            if method == 'Bank Transfer':
                Payment.objects.update_or_create(
                    booking=booking,
                    defaults={
                        'amount': booking.trip.fare_amount,
                        'method': method,
                        'status': 'Pending',
                        'transfer_reference': '',
                        'paid_at': None,
                    },
                )
                messages.info(request, 'Make your bank transfer using the details below. Your booking remains pending until staff verify the payment.')
                return redirect(f'{reverse("passenger_loading:payment", args=[booking.id])}?bank_transfer=1')

            payment_url = request.build_absolute_uri(reverse('passenger_loading:payment', args=[booking.id]))
            cancel_url = f'{payment_url}?cancelled=1'
            try:
                if method == 'PayPal':
                    checkout_url = create_paypal_order(booking, f'{payment_url}?provider=paypal', cancel_url)
                else:
                    checkout_url = create_remita_checkout(booking, request.user, f'{payment_url}?provider=remita')
                return redirect(checkout_url)
            except PaymentProviderError as exc:
                messages.error(request, str(exc))
    else:
        form = PaymentForm()

    bank_transfer = Payment.objects.filter(
        booking=booking,
        method='Bank Transfer',
        status='Pending',
    ).first()
    return render(request, 'payment.html', {
        'booking': booking,
        'form': form,
        'bank_transfer': bank_transfer,
        'bank_transfer_selected': request.GET.get('bank_transfer') == '1',
        'bank_details': {
            'bank_name': settings.BANK_TRANSFER_BANK_NAME,
            'account_number': settings.BANK_TRANSFER_ACCOUNT_NUMBER,
            'account_name': settings.BANK_TRANSFER_ACCOUNT_NAME,
        },
    })


def confirm_payment(booking, method, receipt_url, receipt_pdf_url):
    newly_confirmed = False
    with transaction.atomic():
        payment_record, _ = Payment.objects.select_for_update().get_or_create(
            booking=booking,
            defaults={
                'amount': booking.trip.fare_amount,
                'method': method,
                'status': 'Paid',
                'paid_at': timezone.now(),
            },
        )
        if payment_record.status != 'Paid':
            payment_record.amount = booking.trip.fare_amount
            payment_record.method = method
            payment_record.status = 'Paid'
            payment_record.paid_at = timezone.now()
            payment_record.transfer_reference = (
                payment_record.transfer_reference if method == 'Bank Transfer' else ''
            )
            payment_record.save(update_fields=(
                'amount',
                'method',
                'status',
                'transfer_reference',
                'paid_at',
            ))
            newly_confirmed = True

        if booking.payment_status != 'Paid':
            newly_confirmed = True
        booking.payment_status = 'Paid'
        booking.save(update_fields=['payment_status'])

    if not newly_confirmed:
        return True

    if not booking.passenger.email:
        logger.warning('Payment %s was confirmed but passenger %s has no email address.', payment_record.reference, booking.passenger_id)
        return False

    context = {
        'booking': booking,
        'payment': payment_record,
        'receipt_url': receipt_url,
        'receipt_pdf_url': receipt_pdf_url,
    }
    subject = f'Payment receipt and invoice - Booking {booking.pk}'
    text_body = (
        strip_tags(render_to_string('payment_confirmation_email.html', context))
        + f'\n\nView receipt: {receipt_url}\nDownload PDF: {receipt_pdf_url}'
    )
    html_body = render_to_string('payment_confirmation_email.html', context)
    email = EmailMultiAlternatives(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,
        [booking.passenger.email],
    )
    email.attach_alternative(html_body, 'text/html')
    email.attach(f'receipt-{booking.pk}.pdf', create_receipt_pdf(booking, payment_record), 'application/pdf')
    try:
        sent = email.send()
    except (OSError, smtplib.SMTPException):
        logger.exception('Could not email payment receipt for payment %s.', payment_record.reference)
        return False
    if not sent:
        logger.error('Email backend did not send payment receipt for payment %s.', payment_record.reference)
        return False
    return True
@login_required
def receipt(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('trip', 'trip__route', 'trip__bus', 'passenger'),
        id=booking_id,
        passenger=request.user,
        payment_status='Paid',
    )
    payment_record = get_object_or_404(Payment, booking=booking)
    return render(request, 'receipt.html', {'booking': booking, 'payment': payment_record})


@login_required
def receipt_pdf(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('trip', 'trip__route', 'passenger'),
        id=booking_id,
        passenger=request.user,
        payment_status='Paid',
    )
    payment_record = get_object_or_404(Payment, booking=booking, status='Paid')
    response = HttpResponse(
        create_receipt_pdf(booking, payment_record),
        content_type='application/pdf',
    )
    response['Content-Disposition'] = f'attachment; filename="receipt-{booking.pk}.pdf"'
    return response


@staff_member_required
def admin_reports(request):
    return render(request, 'admin_reports.html', _report_context())


def _report_context():
    total_passengers = Passenger.objects.count()
    total_trips = Trip.objects.count()
    total_bookings = Booking.objects.count()
    revenue = Booking.objects.filter(payment_status='Paid').aggregate(total=Sum('trip__fare_amount'))['total'] or 0

    # Trip-wise occupancy
    trip_stats = []
    trips = Trip.objects.all().order_by('-departure_time')[:20]
    for t in trips:
        booked = t.booking_set.count()
        trip_stats.append({
            'trip': t,
            'booked': booked,
            'capacity': t.bus.capacity,
            'occupancy_percent': round((booked / t.bus.capacity) * 100, 1) if t.bus.capacity else 0,
        })

    context = {
        'total_passengers': total_passengers,
        'total_trips': total_trips,
        'total_bookings': total_bookings,
        'revenue': revenue,
        'trip_stats': trip_stats,
    }
    return context