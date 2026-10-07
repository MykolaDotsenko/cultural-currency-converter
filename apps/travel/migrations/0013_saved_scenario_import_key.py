from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0012_saved_currency"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedscenario",
            name="import_key",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="savedscenario",
            constraint=models.UniqueConstraint(
                condition=Q(import_key__isnull=False),
                fields=("user", "import_key"),
                name="unique_scenario_import_key_per_user",
            ),
        ),
    ]
