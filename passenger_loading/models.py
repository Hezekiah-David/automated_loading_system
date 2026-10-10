from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
import uuid

class Passenger(AbstractUser):
    matric_number = models.CharField(max_length=20, unique=True)
    phone = models.CharField(max_length=15, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.matric_number})"

class Bus(models.Model):
    registration_number = models.CharField(max_length=20, unique=True)
    capacity = models.PositiveIntegerField()
    bus_type = models.CharField(max_length=50)

    def save(self, *args, **kwargs):
        if Bus.objects.exclude(pk=self.pk).exists():
            raise ValidationError('The school can register only one bus.')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.bus_type} - {self.registration_number}"

class Route(models.Model):
    route_name = models.CharField(max_length=100)
    origin = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)

    def __str__(self):
        return self.route_name

class Trip(models.Model):
    STATUS_CHOICES = [
        ('Scheduled', 'Scheduled'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled'),
    ]
    bus = models.ForeignKey(Bus, on_delete=models.CASCADE)
    route = models.ForeignKey(Route, on_delete=models.CASCADE)
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField(blank=True, null=True)
    fare_amount = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Scheduled')

    def __str__(self):
        return f"{self.route.route_name} - {self.departure_time.strftime('%Y-%m-%d %H:%M')}"

    def available_seats(self):
        booked = self.booking_set.count()
        return self.bus.capacity - booked

    def is_full(self):
        return self.available_seats() <= 0

class Booking(models.Model):
    PAYMENT_STATUS = [
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Failed', 'Failed'),
    ]
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE)
    seat_number = models.PositiveIntegerField()
    booking_date = models.DateTimeField(auto_now_add=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='Pending')

    class Meta:
        unique_together = ('trip', 'seat_number')

    def __str__(self):
        passenger_name = self.passenger.get_full_name() or self.passenger.username
        return f"{passenger_name} - Seat {self.seat_number} ({self.trip})"

    # REMOVE the clean() method entirely – it is not needed

class Payment(models.Model):
    METHOD_CHOICES = [
        ('PayPal', 'PayPal'),
        ('Remita', 'Remita'),
        ('Bank Transfer', 'Bank Transfer'),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
    ]
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    method = models.CharField(max_length=30, choices=METHOD_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    transfer_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.reference} - {self.booking}"