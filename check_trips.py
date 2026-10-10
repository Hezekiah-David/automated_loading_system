#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automated_loading_system.settings')
django.setup()

from passenger_loading.models import Trip

trips = Trip.objects.all()
print(f"Total trips in database: {trips.count()}")
print()

if trips.count() > 0:
    print("All Trips:")
    print("-" * 80)
    for trip in trips:
        print(f"ID: {trip.id}")
        print(f"Route: {trip.route.route_name}")
        print(f"Status: {trip.status}")
        print(f"Departure: {trip.departure_time}")
        print(f"Bus: {trip.bus.bus_type} ({trip.bus.registration_number})")
        print(f"Fare: ₦{trip.fare_amount}")
        print()
    
    print("-" * 80)
    scheduled_trips = Trip.objects.filter(status='Scheduled')
    print(f"Scheduled trips only: {scheduled_trips.count()}")
else:
    print("⚠️  No trips found in database!")
    print("Please create trips in the admin panel first.")
