import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("culture", "0005_economic_observation"),
    ]

    operations = [
        migrations.CreateModel(
            name="PublicHolidayObservation",
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
                ("date", models.DateField()),
                ("name", models.CharField(max_length=200)),
                ("national_holiday", models.BooleanField(default=True)),
                ("subdivision_codes", models.JSONField(blank=True, default=list)),
                ("holiday_types", models.JSONField(blank=True, default=list)),
                ("source_name", models.CharField(default="Nager.Date", max_length=120)),
                ("source_url", models.URLField(max_length=700)),
                ("source_retrieved_at", models.DateTimeField()),
                ("is_published", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "country",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="public_holiday_observations",
                        to="countries.country",
                    ),
                ),
            ],
            options={
                "ordering": ("country__name", "date", "name"),
                "indexes": [
                    models.Index(
                        fields=["country", "date"],
                        name="culture_holiday_ctry_date",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("country", "date", "name"),
                        name="public_holiday_observation_identity",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(name=""),
                        name="public_holiday_name_required",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(source_name=""),
                        name="public_holiday_source_name_required",
                    ),
                ],
            },
        ),
    ]
