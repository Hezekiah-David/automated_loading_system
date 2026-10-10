from django.contrib import admin
from django.contrib import messages
from django.urls import reverse
from .models import Passenger, Bus, Route, Trip, Booking, Payment
from .views import confirm_payment

@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = ('username', 'matric_number', 'email', 'phone', 'is_staff')
    search_fields = ('username', 'matric_number', 'email')
    list_filter = ('is_staff', 'is_active')

@admin.register(Bus)
class BusAdmin(admin.ModelAdmin):
    list_display = ('registration_number', 'bus_type', 'capacity')
    search_fields = ('registration_number', 'bus_type')

    def has_add_permission(self, request):
        return not Bus.objects.exists() and super().has_add_permission(request)

@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('route_name', 'origin', 'destination')
    search_fields = ('route_name',)

@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('id', 'route', 'bus', 'departure_time', 'fare_amount', 'status')
    list_filter = ('status', 'route')
    search_fields = ('route__route_name', 'bus__registration_number')
    date_hierarchy = 'departure_time'

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'trip', 'passenger', 'seat_number', 'payment_status', 'booking_date')
    list_filter = ('payment_status', 'trip')
    search_fields = ('passenger__username', 'trip__route__route_name')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('reference', 'booking', 'amount', 'method', 'status', 'transfer_reference', 'paid_at')
    list_filter = ('method', 'status')
    search_fields = ('reference', 'transfer_reference', 'booking__passenger__username')
    readonly_fields = ('reference', 'amount', 'booking', 'method', 'status', 'transfer_reference', 'paid_at')
    actions = ('confirm_bank_transfers',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Confirm selected bank transfers and email receipts')
    def confirm_bank_transfers(self, request, queryset):
        pending_transfers = queryset.filter(method='Bank Transfer', status='Pending')
        confirmed = 0
        email_failures = 0
        for payment in pending_transfers.select_related('booking', 'booking__passenger'):
            receipt_url = request.build_absolute_uri(
                reverse('passenger_loading:receipt', args=[payment.booking_id])
            )
            receipt_pdf_url = request.build_absolute_uri(
                reverse('passenger_loading:receipt_pdf', args=[payment.booking_id])
            )
            email_sent = confirm_payment(
                payment.booking,
                'Bank Transfer',
                receipt_url,
                receipt_pdf_url,
            )
            confirmed += 1
            if not email_sent:
                email_failures += 1

        if confirmed:
            self.message_user(
                request,
                f'{confirmed} bank transfer(s) confirmed.',
                messages.SUCCESS,
            )
        if email_failures:
            self.message_user(
                request,
                f'{email_failures} payment(s) were confirmed, but their receipt emails could not be sent. Check email configuration and passenger addresses.',
                messages.WARNING,
            )
        if not confirmed:
            self.message_user(
                request,
                'No pending bank transfers were selected.',
                messages.WARNING,
            )