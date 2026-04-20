"""
Management command: create_default_admin

Creates a default admin account for local development / first-run setup.
Safe to run multiple times — skips creation if the email already exists.

Usage:
    python manage.py create_default_admin
"""

from django.core.management.base import BaseCommand

from apps.users.models import User


class Command(BaseCommand):
    help = "Create the default admin user (admin@gmail.com / 12345678) if it doesn't exist."

    def handle(self, *args, **options):
        email = "admin@gmail.com"
        password = "12345678"

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f"Admin '{email}' already exists — skipping."))
            return

        user = User.objects.create_superuser(email=email, password=password)
        user.name = "Admin"
        user.role = User.Role.ADMIN
        user.save(update_fields=["name", "role", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Default admin created: {email} / {password}"))
