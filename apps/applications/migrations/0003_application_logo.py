from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="logo",
            field=models.FileField(blank=True, null=True, upload_to="team_logos/"),
        ),
    ]
