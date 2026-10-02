import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0006_saved_scenario_spend_entries"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedPlace",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "city",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.city",
                    ),
                ),
                (
                    "country",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.country",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_places",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "-updated_at"],
                        name="travel_place_user_upd_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("city__isnull", True)),
                        fields=("user", "country"),
                        name="unique_saved_place_country",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("city__isnull", False)),
                        fields=("user", "city"),
                        name="unique_saved_place_city",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SavedComparison",
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
                ("fingerprint", models.CharField(max_length=64)),
                ("source_amount", models.DecimalField(decimal_places=12, max_digits=40)),
                ("duration_days", models.PositiveSmallIntegerField()),
                ("travelers", models.PositiveSmallIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "left_city",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.city",
                    ),
                ),
                (
                    "left_country",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.country",
                    ),
                ),
                (
                    "right_city",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.city",
                    ),
                ),
                (
                    "right_country",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.country",
                    ),
                ),
                (
                    "source_currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.currency",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="saved_comparisons",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "-updated_at"],
                        name="travel_cmp_user_upd_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "fingerprint"),
                        name="unique_saved_comparison",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("source_amount__gte", 0)),
                        name="saved_cmp_amount_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("duration_days__gte", 1),
                            ("duration_days__lte", 365),
                        ),
                        name="saved_cmp_duration_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("travelers__gte", 1),
                            ("travelers__lte", 20),
                        ),
                        name="saved_cmp_travelers_range",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SavedComparisonBudgetItem",
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
                ("category", models.CharField(max_length=24)),
                (
                    "units_per_person_per_day",
                    models.DecimalField(decimal_places=2, max_digits=8),
                ),
                (
                    "comparison",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="budget_items",
                        to="travel.savedcomparison",
                    ),
                ),
            ],
            options={
                "ordering": ("category", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("comparison", "category"),
                        name="unique_saved_cmp_category",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("units_per_person_per_day__gt", 0),
                            ("units_per_person_per_day__lte", 100),
                        ),
                        name="saved_cmp_units_range",
                    ),
                ],
            },
        ),
    ]
