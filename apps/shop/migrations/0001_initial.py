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
            name="ShopOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("stripe_session_id", models.CharField(max_length=255, unique=True)),
                ("product_name", models.CharField(max_length=500)),
                ("amount_cents", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[("paid", "Paid")],
                        db_index=True,
                        default="paid",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shop_orders",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "shop_orders",
                "ordering": ["-created_at"],
            },
        ),
    ]
