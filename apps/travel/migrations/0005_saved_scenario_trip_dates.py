from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0004_saved_scenarios"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="savedscenario",
            name="scenario_travel_dates_ordered",
        ),
        migrations.AddConstraint(
            model_name="savedscenario",
            constraint=models.CheckConstraint(
                condition=models.Q(("travel_end_date__isnull", True))
                | (
                    models.Q(("travel_start_date__isnull", False))
                    & models.Q(("travel_end_date__gte", models.F("travel_start_date")))
                ),
                name="scenario_travel_dates_ordered",
            ),
        ),
    ]
