from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0013_saved_scenario_plan_revision"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedscenarioplanrevision",
            name="category_snapshot",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
