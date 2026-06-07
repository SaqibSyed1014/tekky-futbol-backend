import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("teams", "0003_m3_team_status_invite_membership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamKitSelection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kit_slug", models.CharField(
                    max_length=20,
                    choices=[
                        ("north-1", "north-1"), ("north-2", "north-2"), ("north-3", "north-3"),
                        ("north-4", "north-4"), ("north-5", "north-5"), ("north-6", "north-6"),
                        ("north-7", "north-7"), ("north-8", "north-8"),
                        ("south-1", "south-1"), ("south-2", "south-2"), ("south-3", "south-3"),
                        ("south-4", "south-4"), ("south-5", "south-5"), ("south-6", "south-6"),
                        ("south-7", "south-7"), ("south-8", "south-8"),
                    ],
                )),
                ("is_locked", models.BooleanField(db_index=True, default=False)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("team", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="kit_selection",
                    to="teams.team",
                )),
            ],
            options={"db_table": "team_kit_selections"},
        ),
        migrations.CreateModel(
            name="KitOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("jersey_size", models.CharField(
                    max_length=5,
                    choices=[("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"), ("XXL", "XXL")],
                )),
                ("shorts_size", models.CharField(
                    max_length=5,
                    choices=[("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL"), ("XXL", "XXL")],
                )),
                ("socks_size", models.CharField(
                    max_length=5,
                    choices=[("S", "S"), ("M", "M"), ("L", "L"), ("XL", "XL")],
                )),
                ("name_on_kit", models.CharField(blank=True, default="", max_length=20)),
                ("number_on_kit", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("team", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="kit_orders",
                    to="teams.team",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="kit_orders",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"db_table": "kit_orders", "ordering": ["created_at"]},
        ),
        migrations.AddConstraint(
            model_name="kitorder",
            constraint=models.UniqueConstraint(
                fields=["team", "user"],
                name="kitorder_unique_team_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="kitorder",
            constraint=models.UniqueConstraint(
                condition=models.Q(number_on_kit__isnull=False),
                fields=["team", "number_on_kit"],
                name="kitorder_unique_team_number",
            ),
        ),
    ]
