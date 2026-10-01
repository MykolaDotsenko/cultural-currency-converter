import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0005_saved_scenario_trip_dates"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedScenarioSpendEntry",
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
                ("amount", models.DecimalField(decimal_places=12, max_digits=40)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("manual", "Manual entry"),
                            ("camera", "Camera-confirmed"),
                        ],
                        default="manual",
                        max_length=16,
                    ),
                ),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="spend_entries",
                        to="travel.savedscenario",
                    ),
                ),
            ],
            options={
                "ordering": ("-recorded_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["scenario", "-recorded_at"],
                        name="travel_scenario_spend_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("amount__gt", 0),
                            ("amount__lte", 1000000000),
                        ),
                        name="scenario_spend_amount_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("source__in", ["manual", "camera"])),
                        name="scenario_spend_source_valid",
                    ),
                ],
            },
        ),
    ]
