"""
Make participant-info fields on WaiverSignature optional.

The waiver UI no longer requires date of birth, address, or emergency-contact
details — only the agreement clauses, printed name, and signature are mandatory.
Existing rows are unaffected (they already have values for these columns).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waivers', '0001_initial'),
    ]

    operations = [
        # date_of_birth: was NOT NULL DateField, now nullable
        migrations.AlterField(
            model_name='waiversignature',
            name='date_of_birth',
            field=models.DateField(blank=True, null=True),
        ),
        # address: was NOT NULL TextField, now blank-allowed with default
        migrations.AlterField(
            model_name='waiversignature',
            name='address',
            field=models.TextField(blank=True, default=''),
        ),
        # emergency contact fields: were NOT NULL, now blank with default
        migrations.AlterField(
            model_name='waiversignature',
            name='emergency_contact_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='waiversignature',
            name='emergency_contact_rel',
            field=models.CharField(
                blank=True, default='', max_length=50,
                verbose_name='Emergency contact relationship',
            ),
        ),
        migrations.AlterField(
            model_name='waiversignature',
            name='emergency_contact_phone',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
