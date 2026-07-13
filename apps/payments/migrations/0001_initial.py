from decimal import Decimal
import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id",               models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user",             models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="payment", to=settings.AUTH_USER_MODEL)),
                ("reference_number", models.CharField(max_length=100, unique=True)),
                ("transaction_id",   models.CharField(blank=True, max_length=100, null=True)),
                ("amount",           models.DecimalField(decimal_places=2, default=Decimal("700.00"), max_digits=8)),
                ("currency",         models.CharField(default="USD", max_length=3)),
                ("status",           models.CharField(choices=[("pending","Pending"),("paid","Paid"),("failed","Failed"),("cancelled","Cancelled")], db_index=True, default="pending", max_length=20)),
                ("paid_at",          models.DateTimeField(blank=True, null=True)),
                ("created_at",       models.DateTimeField(auto_now_add=True)),
                ("updated_at",       models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "payments", "ordering": ["-created_at"]},
        ),
    ]
