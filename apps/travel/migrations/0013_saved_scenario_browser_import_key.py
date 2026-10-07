from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0012_saved_currency"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedscenario",
            name="browser_import_key",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="savedscenario",
            constraint=models.UniqueConstraint(
                fields=("user", "browser_import_key"),
                condition=Q(browser_import_key__isnull=False),
                name="unique_scenario_browser_import",
            ),
        ),
    ]
