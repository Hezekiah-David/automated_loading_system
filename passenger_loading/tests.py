from unittest.mock import patch
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core import mail
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from .models import Booking, Bus, Payment, Route, Trip
from .payments import PaymentProviderError


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PassengerBookingTests(TestCase):
	def setUp(self):
		self.passenger = get_user_model().objects.create_user(
			username='student1',
			first_name='Ada',
			last_name='Okafor',
			email='ada@example.com',
			matric_number='MAT001',
			password='StrongPass123!',
		)
		self.bus = Bus.objects.create(registration_number='PLP-001', capacity=30, bus_type='School bus')
		route = Route.objects.create(route_name='Campus', origin='Town', destination='Campus')
		self.trip = Trip.objects.create(
			bus=self.bus,
			route=route,
			departure_time='2027-01-01T09:00:00Z',
			fare_amount='1500.00',
		)
		self.booking = Booking.objects.create(
			trip=self.trip,
			passenger=self.passenger,
			seat_number=1,
		)
		self.client.force_login(self.passenger)

	def test_home_is_available_without_login(self):
		self.client.logout()
		response = self.client.get(reverse('passenger_loading:home'))
		self.assertEqual(response.status_code, 200)

	def test_staff_home_includes_scrollable_reports(self):
		self.passenger.is_staff = True
		self.passenger.save(update_fields=['is_staff'])
		response = self.client.get(reverse('passenger_loading:home'))
		self.assertContains(response, 'id="reports"')
		self.assertContains(response, 'Recent trip occupancy')

	def test_second_school_bus_is_rejected(self):
		with self.assertRaises(ValidationError):
			Bus.objects.create(registration_number='PLP-002', capacity=20, bus_type='Extra bus')

	def test_payment_post_redirects_to_selected_provider(self):
		with patch('passenger_loading.views.create_paypal_order', return_value='https://paypal.example/approve') as create_order:
			response = self.client.post(
				reverse('passenger_loading:payment', args=[self.booking.pk]),
				{'method': 'PayPal'},
			)
		self.assertRedirects(response, 'https://paypal.example/approve', fetch_redirect_response=False)
		create_order.assert_called_once()
		self.booking.refresh_from_db()
		self.assertEqual(self.booking.payment_status, 'Pending')
		self.assertFalse(Payment.objects.filter(booking=self.booking).exists())

	def test_provider_error_does_not_mark_booking_paid(self):
		with patch(
			'passenger_loading.views.create_paypal_order',
			side_effect=PaymentProviderError('PayPal credentials are not configured.'),
		):
			response = self.client.post(
				reverse('passenger_loading:payment', args=[self.booking.pk]),
				{'method': 'PayPal'},
			)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'PayPal credentials are not configured.')
		self.booking.refresh_from_db()
		self.assertEqual(self.booking.payment_status, 'Pending')
		self.assertFalse(Payment.objects.filter(booking=self.booking).exists())

	def test_unverified_provider_return_does_not_mark_booking_paid(self):
		with patch(
			'passenger_loading.views.verify_paypal_return',
			side_effect=PaymentProviderError('PayPal has not completed this payment.'),
		):
			response = self.client.get(
				reverse('passenger_loading:payment', args=[self.booking.pk]),
				{'provider': 'paypal', 'token': 'unverified-order'},
			)
		self.assertEqual(response.status_code, 200)
		self.booking.refresh_from_db()
		self.assertEqual(self.booking.payment_status, 'Pending')
		self.assertFalse(Payment.objects.filter(booking=self.booking).exists())

	def test_verified_provider_return_confirms_booking_with_passenger_name(self):
		with patch('passenger_loading.views.verify_paypal_return'):
			response = self.client.get(
				reverse('passenger_loading:payment', args=[self.booking.pk]),
				{'provider': 'paypal', 'token': 'provider-order-id'},
			)
		self.assertRedirects(
			response,
			reverse('passenger_loading:receipt', args=[self.booking.pk]),
			fetch_redirect_response=False,
		)
		self.booking.refresh_from_db()
		self.assertEqual(self.booking.payment_status, 'Paid')
		self.assertContains(self.client.get(reverse('passenger_loading:receipt', args=[self.booking.pk])), 'Ada Okafor')
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('receipt and invoice', mail.outbox[0].subject.lower())
		self.assertIn('1500.00', mail.outbox[0].alternatives[0][0])
		self.assertEqual(mail.outbox[0].attachments[0][0], f'receipt-{self.booking.pk}.pdf')
		self.assertEqual(mail.outbox[0].attachments[0][2], 'application/pdf')

	def test_bank_transfer_is_recorded_pending_with_current_trip_fare(self):
		self.trip.fare_amount = '1850.00'
		self.trip.save(update_fields=['fare_amount'])

		response = self.client.post(
			reverse('passenger_loading:payment', args=[self.booking.pk]),
			{'method': 'Bank Transfer'},
		)

		self.assertRedirects(
			response,
			f"{reverse('passenger_loading:payment', args=[self.booking.pk])}?bank_transfer=1",
			fetch_redirect_response=False,
		)
		payment = Payment.objects.get(booking=self.booking)
		self.assertEqual(payment.amount, Decimal('1850.00'))
		self.assertEqual(payment.method, 'Bank Transfer')
		self.assertEqual(payment.status, 'Pending')
		self.assertEqual(payment.transfer_reference, '')
		self.booking.refresh_from_db()
		self.assertEqual(self.booking.payment_status, 'Pending')
		self.assertEqual(len(mail.outbox), 0)
		instructions = self.client.get(response.url)
		self.assertContains(instructions, '2110968009')
		self.assertContains(instructions, 'Make a transfer')
		self.assertNotContains(instructions, 'name="transfer_reference"')

	def test_bank_transfer_details_and_pending_instructions_are_shown(self):
		Payment.objects.create(
			booking=self.booking,
			amount=self.trip.fare_amount,
			method='Bank Transfer',
			status='Pending',
			transfer_reference='UBA-TRANSFER-123',
		)

		response = self.client.get(reverse('passenger_loading:payment', args=[self.booking.pk]))

		self.assertContains(response, '2110968009')
		self.assertContains(response, 'Hezekiah Gocheka Rumson')
		self.assertNotContains(response, 'UBA-TRANSFER-123')
		self.assertContains(response, 'No transfer reference is needed')
		self.assertContains(response, 'awaiting staff verification')
		self.assertNotContains(response, 'name="transfer_reference"')

	def test_admin_confirmation_marks_bank_transfer_paid_and_emails_invoice(self):
		payment = Payment.objects.create(
			booking=self.booking,
			amount=self.trip.fare_amount,
			method='Bank Transfer',
			status='Pending',
			transfer_reference='UBA-TRANSFER-123',
		)
		staff = get_user_model().objects.create_superuser(
			username='admin',
			email='admin@example.com',
			matric_number='ADMIN001',
			password='StrongPass123!',
		)
		self.client.force_login(staff)

		response = self.client.post(
			reverse('admin:passenger_loading_payment_changelist'),
			{
				'action': 'confirm_bank_transfers',
				'_selected_action': str(payment.pk),
			},
		)

		self.assertEqual(response.status_code, 302)
		payment.refresh_from_db()
		self.booking.refresh_from_db()
		self.assertEqual(payment.status, 'Paid')
		self.assertIsNotNone(payment.paid_at)
		self.assertEqual(self.booking.payment_status, 'Paid')
		self.assertEqual(len(mail.outbox), 1)
		self.assertIn('NGN 1500.00', mail.outbox[0].alternatives[0][0])
		self.assertIn('receipt/invoice', mail.outbox[0].alternatives[0][0])
		self.assertEqual(mail.outbox[0].attachments[0][0], f'receipt-{self.booking.pk}.pdf')
		self.assertEqual(mail.outbox[0].attachments[0][2], 'application/pdf')

	def test_passenger_can_download_paid_receipt_as_pdf(self):
		Payment.objects.create(
			booking=self.booking,
			amount=self.trip.fare_amount,
			method='Bank Transfer',
			status='Paid',
		)
		self.booking.payment_status = 'Paid'
		self.booking.save(update_fields=['payment_status'])

		response = self.client.get(
			reverse('passenger_loading:receipt_pdf', args=[self.booking.pk])
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response['Content-Type'], 'application/pdf')
		self.assertIn(f'receipt-{self.booking.pk}.pdf', response['Content-Disposition'])
		self.assertTrue(response.content.startswith(b'%PDF'))
