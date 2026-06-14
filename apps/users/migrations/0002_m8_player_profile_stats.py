from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        # ── Public profile flag ───────────────────────────────────────────────
        migrations.AddField(
            model_name="playerprofile",
            name="is_public",
            field=models.BooleanField(default=False, db_index=True),
        ),
        # ── Personal profile link ─────────────────────────────────────────────
        migrations.AddField(
            model_name="playerprofile",
            name="profile_link",
            field=models.URLField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="profile_link_status",
            field=models.CharField(
                max_length=10,
                choices=[("none", "None"), ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
                default="none",
                db_index=True,
            ),
        ),
        # ── Stats ─────────────────────────────────────────────────────────────
        migrations.AddField(
            model_name="playerprofile",
            name="goals",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="assists",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="matches_played",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="mvps",
            field=models.PositiveIntegerField(default=0),
        ),
        # ── Upcoming match ────────────────────────────────────────────────────
        migrations.AddField(
            model_name="playerprofile",
            name="upcoming_opponent",
            field=models.CharField(max_length=100, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="upcoming_date",
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="upcoming_kickoff",
            field=models.CharField(max_length=20, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="upcoming_location",
            field=models.CharField(max_length=200, blank=True, default=""),
        ),
        # ── Team standing ─────────────────────────────────────────────────────
        migrations.AddField(
            model_name="playerprofile",
            name="team_rank",
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="team_wins",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="team_losses",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="team_draws",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="playerprofile",
            name="team_goal_difference",
            field=models.SmallIntegerField(default=0),
        ),
        # ── Index for is_public ───────────────────────────────────────────────
        migrations.AddIndex(
            model_name="playerprofile",
            index=models.Index(fields=["is_public"], name="playerprofile_is_public_idx"),
        ),
    ]
