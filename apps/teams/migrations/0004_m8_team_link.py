from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0003_m3_team_status_invite_membership"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="team_link",
            field=models.URLField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="team",
            name="team_link_status",
            field=models.CharField(
                max_length=10,
                choices=[("none", "None"), ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
                default="none",
                db_index=True,
            ),
        ),
    ]
