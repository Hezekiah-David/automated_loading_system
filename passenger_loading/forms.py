from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Passenger, Booking

class PassengerRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True, label='First name')
    last_name = forms.CharField(max_length=150, required=True, label='Last name')
    matric_number = forms.CharField(max_length=20, required=True)
    phone = forms.CharField(max_length=15, required=False)
    email = forms.EmailField(required=True)

    class Meta:
        model = Passenger
        fields = ('username', 'first_name', 'last_name', 'matric_number', 'email', 'phone', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user

class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ('seat_number',)
        widgets = {
            'seat_number': forms.NumberInput(attrs={
                'min': 1, 
                'class': 'form-control',
                'placeholder': 'Enter seat number'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.trip = kwargs.pop('trip', None)
        super().__init__(*args, **kwargs)
        if self.trip:
            self.fields['seat_number'].widget.attrs['max'] = self.trip.bus.capacity
            self.fields['seat_number'].help_text = f"Available seats: 1-{self.trip.bus.capacity}"

    def clean_seat_number(self):
        seat = self.cleaned_data.get('seat_number')
        if not seat:
            raise forms.ValidationError("Seat number is required.")
        
        if self.trip:
            # Check if seat is within bus capacity
            if seat < 1 or seat > self.trip.bus.capacity:
                raise forms.ValidationError(f"Seat must be between 1 and {self.trip.bus.capacity}.")
            
            # Check if seat is already booked
            if Booking.objects.filter(trip=self.trip, seat_number=seat).exists():
                raise forms.ValidationError("This seat is already booked for this trip.")
        return seat

class PaymentForm(forms.Form):
    method = forms.ChoiceField(choices=(
        ('PayPal', 'PayPal'),
        ('Remita', 'Remita'),
        ('Bank Transfer', 'Bank Transfer'),
    ))