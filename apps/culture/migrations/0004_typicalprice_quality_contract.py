from django.db import migrations, models


def backfill_typical_price_units(apps, schema_editor):
    TypicalPrice = apps.get_model("culture", "TypicalPrice")
    category_units = {
        "coffee": "serving",
        "casual_meal": "meal",
        "transit": "ride",
        "groceries": "basket",
        "other": "item",
    }
    for category, unit in category_units.items():
        TypicalPrice.objects.filter(category=category).update(unit=unit)


class Migration(migrations.Migration):
    dependencies = [
        ("culture", "0003_typicalprice_city_ref"),
    ]

    operations = [
        migrations.AddField(
            model_name="typicalprice",
            name="unit",
            field=models.CharField(
                choices=[
                    ("serving", "Serving"),
                    ("meal", "Meal"),
                    ("ride", "Ride"),
                    ("basket", "Basket"),
                    ("item", "Item"),
                ],
                default="item",
                max_length=16,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(
            backfill_typical_price_units,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="typicalprice",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(category="coffee", unit="serving")
                    | models.Q(category="casual_meal", unit="meal")
                    | models.Q(category="transit", unit="ride")
                    | models.Q(category="groceries", unit="basket")
                    | models.Q(category="other", unit="item")
                ),
                name="typical_price_category_unit",
            ),
        ),
        migrations.AddConstraint(
            model_name="typicalprice",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_published=False)
                    | models.Q(city="")
                    | models.Q(city_ref__isnull=False)
                ),
                name="typical_price_published_city_is_canonical",
            ),
        ),
        migrations.AddConstraint(
            model_name="typicalprice",
            constraint=models.UniqueConstraint(
                fields=("country", "city_ref", "category", "unit", "label", "observed_at"),
                condition=models.Q(city_ref__isnull=False),
                name="typical_price_city_observation_identity",
            ),
        ),
        migrations.AddConstraint(
            model_name="typicalprice",
            constraint=models.UniqueConstraint(
                fields=("country", "category", "unit", "label", "observed_at"),
                condition=models.Q(city_ref__isnull=True, city=""),
                name="typical_price_national_observation_identity",
            ),
        ),
    ]
