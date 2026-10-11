# Created for explicitly versioned saved-budget planning.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0012_saved_currency"),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedScenarioPlanRevision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("revision", models.PositiveSmallIntegerField()),
                ("travelers", models.PositiveSmallIntegerField()),
                ("duration_days", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "scenario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_revisions",
                        to="travel.savedscenario",
                    ),
                ),
            ],
            options={
                "ordering": ("revision",),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scenario", "revision"), name="scenario_plan_revision_unique"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(travelers__gte=1, travelers__lte=20),
                        name="scenario_plan_revision_travelers_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(duration_days__isnull=True)
                        | models.Q(duration_days__gte=1, duration_days__lte=365),
                        name="scenario_plan_revision_days_valid",
                    ),
                ],
            },
        ),
    ]
