from django.urls import path
from . import views

app_name = 'passenger_loading'

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('trips/', views.trips, name='trips'),
    path('book/<int:trip_id>/', views.book_seat, name='book_seat'),
    path('payment/<int:booking_id>/', views.payment, name='payment'),
    path('receipt/<int:booking_id>/', views.receipt, name='receipt'),
    path('receipt/<int:booking_id>/pdf/', views.receipt_pdf, name='receipt_pdf'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),
    path('admin-reports/', views.admin_reports, name='admin_reports'),
]