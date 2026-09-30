import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("countries", "0002_currency_coverage_bounds"),
    ]

    operations = [
        migrations.CreateModel(
            name="City",
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
                ("slug", models.SlugField(max_length=140)),
                ("name", models.CharField(max_length=120)),
                ("region", models.CharField(blank=True, max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "country",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cities",
                        to="countries.country",
                    ),
                ),
            ],
            options={
                "ordering": ("country__name", "name", "slug"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("country", "slug"),
                        name="unique_city_slug_per_country",
                    ),
                ],
            },
        ),
    ]
