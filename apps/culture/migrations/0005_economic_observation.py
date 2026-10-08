import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("culture", "0004_typicalprice_quality_contract"),
    ]

    operations = [
        migrations.CreateModel(
            name="EconomicObservation",
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
                    "source",
                    models.CharField(
                        choices=[
                            ("world_bank", "World Bank"),
                            ("eurostat", "Eurostat"),
                            ("oecd", "OECD"),
                        ],
                        max_length=24,
                    ),
                ),
                (
                    "indicator",
                    models.CharField(
                        choices=[
                            (
                                "inflation_yoy",
                                "Consumer price inflation, year over year",
                            ),
                            ("price_level_index", "Comparative price level index"),
                            (
                                "price_level_ratio",
                                "Price level ratio to US benchmark",
                            ),
                        ],
                        max_length=32,
                    ),
                ),
                ("category", models.CharField(default="all_items", max_length=64)),
                ("value", models.DecimalField(decimal_places=6, max_digits=18)),
                ("unit", models.CharField(max_length=48)),
                ("benchmark_label", models.CharField(blank=True, max_length=120)),
                ("period_start", models.DateField()),
                (
                    "frequency",
                    models.CharField(
                        choices=[("monthly", "Monthly"), ("annual", "Annual")],
                        max_length=12,
                    ),
                ),
                (
                    "observation_status",
                    models.CharField(
                        choices=[
                            ("final", "Final"),
                            ("preliminary", "Preliminary"),
                            ("estimate", "Estimate"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("source_dataset", models.CharField(max_length=120)),
                ("source_name", models.CharField(max_length=120)),
                ("source_url", models.URLField(max_length=700)),
                ("source_retrieved_at", models.DateTimeField()),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "country",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="economic_observations",
                        to="countries.country",
                    ),
                ),
            ],
            options={
                "ordering": (
                    "country__name",
                    "indicator",
                    "-period_start",
                    "source",
                ),
                "indexes": [
                    models.Index(
                        fields=["country", "indicator", "-period_start"],
                        name="culture_econ_ctry_ind_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "country",
                            "source",
                            "indicator",
                            "category",
                            "period_start",
                        ),
                        name="economic_observation_identity",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(unit=""),
                        name="economic_observation_unit_required",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(source_dataset=""),
                        name="economic_observation_dataset_required",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(source_name=""),
                        name="economic_observation_source_name_required",
                    ),
                ],
            },
        ),
    ]
