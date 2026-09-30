from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("countries", "0003_city"),
        ("travel", "0003_portable_favourite_identity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedScenario",
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
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("trip", "Trip"),
                            ("budget", "Budget"),
                            ("shopping", "Shopping"),
                        ],
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=120)),
                ("source_amount", models.DecimalField(decimal_places=12, max_digits=40)),
                ("duration_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("travelers", models.PositiveSmallIntegerField(default=1)),
                ("travel_start_date", models.DateField(blank=True, null=True)),
                ("travel_end_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "destination_city",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.city",
                    ),
                ),
                (
                    "destination_country",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.country",
                    ),
                ),
                (
                    "destination_currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="countries.currency",
                    ),
                ),
                (
                    "source_country",
                    models.ForeignKey(
                        blank=True,
                        null=True,
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
                        related_name="saved_scenarios",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "-updated_at"],
                        name="travel_scenario_user_updated_idx",
                    ),
                    models.Index(
                        fields=["user", "kind", "-updated_at"],
                        name="travel_scenario_user_kind_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("kind__in", ["trip", "budget", "shopping"])),
                        name="scenario_kind_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("source_amount__gte", 0)),
                        name="scenario_source_amount_non_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("duration_days__isnull", True))
                        | models.Q(("duration_days__gte", 1), ("duration_days__lte", 365)),
                        name="scenario_duration_days_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("travelers__gte", 1), ("travelers__lte", 20)),
                        name="scenario_travelers_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("travel_start_date__isnull", True))
                        | models.Q(("travel_end_date__isnull", True))
                        | models.Q(("travel_end_date__gte", models.F("travel_start_date"))),
                        name="scenario_travel_dates_ordered",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("destination_city__isnull", True))
                        | models.Q(("destination_country__isnull", False)),
                        name="scenario_city_requires_country",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("kind", "shopping"))
                        | models.Q(("destination_country__isnull", False)),
                        name="scenario_travel_kinds_require_destination",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SavedScenarioBudgetItem",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="budget_items",
                        to="travel.savedscenario",
                    ),
                ),
            ],
            options={
                "ordering": ("category", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scenario", "category"),
                        name="unique_scenario_budget_category",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("units_per_person_per_day__gt", 0))
                        & models.Q(("units_per_person_per_day__lte", 100)),
                        name="scenario_budget_units_range",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SavedScenarioObservation",
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
                (
                    "kind",
                    models.CharField(
                        choices=[("initial", "Initial save"), ("recheck", "Re-check")],
                        max_length=16,
                    ),
                ),
                ("input_amount", models.DecimalField(decimal_places=12, max_digits=40)),
                ("output_amount", models.DecimalField(decimal_places=12, max_digits=40)),
                ("rate", models.DecimalField(decimal_places=18, max_digits=40)),
                ("effective_date", models.DateField()),
                ("fetched_at", models.DateTimeField()),
                ("provider_keys", models.JSONField(default=list)),
                ("stale", models.BooleanField(default=False)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="observations",
                        to="travel.savedscenario",
                    ),
                ),
            ],
            options={
                "ordering": ("-recorded_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["scenario", "-recorded_at"],
                        name="travel_scenario_obs_time_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("kind__in", ["initial", "recheck"])),
                        name="scenario_observation_kind_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("input_amount__gte", 0)),
                        name="scenario_observation_input_non_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("output_amount__gte", 0)),
                        name="scenario_observation_output_non_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("rate__gt", 0)),
                        name="scenario_observation_rate_positive",
                    ),
                ],
            },
        ),
    ]
