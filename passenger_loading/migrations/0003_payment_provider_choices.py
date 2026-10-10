from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('passenger_loading', '0002_payment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='method',
            field=models.CharField(
                choices=[('PayPal', 'PayPal'), ('Remita', 'Remita')],
                max_length=30,
            ),
        ),
    ]