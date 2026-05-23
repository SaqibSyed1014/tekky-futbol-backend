"""
Add minor/guardian fields to WaiverSignature and relax printed_name/signature_image
to blank-allowed so minor submissions (which use guardian fields instead) are valid.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waivers', '0002_waiver_optional_participant_fields'),
    ]

    operations = [
        # ── is_minor flag ─────────────────────────────────────────────────────
        migrations.AddField(
            model_name='waiversignature',
            name='is_minor',
            field=models.BooleanField(default=False),
        ),

        # ── participant phone ─────────────────────────────────────────────────
        migrations.AddField(
            model_name='waiversignature',
            name='participant_phone',
            field=models.CharField(blank=True, default='', max_length=20),
        ),

        # ── guardian fields ───────────────────────────────────────────────────
        migrations.AddField(
            model_name='waiversignature',
            name='guardian_signature',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='waiversignature',
            name='guardian_name_printed',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='waiversignature',
            name='guardian_email',
            field=models.EmailField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='waiversignature',
            name='guardian_phone',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='waiversignature',
            name='guardian_type',
            field=models.CharField(blank=True, default='', max_length=20),
        ),

        # ── relax printed_name and signature_image (adults required via validate()) ──
        migrations.AlterField(
            model_name='waiversignature',
            name='printed_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='waiversignature',
            name='signature_image',
            field=models.TextField(blank=True, default=''),
        ),

        # ── index on is_minor ─────────────────────────────────────────────────
        migrations.AddIndex(
            model_name='waiversignature',
            index=models.Index(fields=['is_minor'], name='waiver_is_minor_idx'),
        ),
    ]
