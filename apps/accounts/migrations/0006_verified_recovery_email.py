"""Add owner-scoped recovery email identity without trusting existing User.email."""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_explanation_preferences"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VerifiedRecoveryEmail",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("email", models.EmailField(max_length=254)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("verification_nonce", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recovery_email_identity",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        Lower("email"),
                        condition=models.Q(verified_at__isnull=False),
                        name="unique_verified_recovery_email_ci",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(verified_at__isnull=True) | ~models.Q(email=""),
                        name="verified_recovery_email_nonempty",
                    ),
                ],
            },
        ),
    ]
