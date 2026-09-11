import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_m8_player_profile_stats"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("admin", "Admin"), ("player", "Player"), ("fan", "Fan")],
                db_index=True,
                default="player",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="google_id",
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="user",
            name="apple_id",
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
        migrations.CreateModel(
            name="FanProfile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "favorite_division",
                    models.CharField(
                        blank=True,
                        choices=[("north", "North Court"), ("south", "South Court")],
                        default="",
                        max_length=10,
                    ),
                ),
                ("zip_code", models.CharField(blank=True, default="", max_length=5)),
                ("shipping_address", models.CharField(blank=True, default="", max_length=200)),
                ("shipping_city", models.CharField(blank=True, default="", max_length=100)),
                ("shipping_state", models.CharField(blank=True, default="", max_length=50)),
                (
                    "shirt_size",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("XS", "XS"),
                            ("S", "S"),
                            ("M", "M"),
                            ("L", "L"),
                            ("XL", "XL"),
                            ("XXL", "XXL"),
                        ],
                        default="",
                        max_length=4,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fan_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "fan_profiles",
            },
        ),
    ]
