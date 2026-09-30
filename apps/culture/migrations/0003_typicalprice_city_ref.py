import django.db.models.deletion
from django.db import migrations, models
from django.utils.text import slugify


def backfill_price_city_refs(apps, schema_editor):
    City = apps.get_model("countries", "City")
    TypicalPrice = apps.get_model("culture", "TypicalPrice")

    rows = (
        TypicalPrice.objects.exclude(city="")
        .order_by("country_id", "city", "pk")
        .values("pk", "country_id", "city")
    )
    for row in rows.iterator():
        display_name = " ".join(str(row["city"]).split())
        base_slug = slugify(display_name) or f"city-{row['pk']}"
        slug = base_slug
        suffix = 2

        while True:
            existing = City.objects.filter(
                country_id=row["country_id"],
                slug=slug,
            ).first()
            if existing is None:
                city = City.objects.create(
                    country_id=row["country_id"],
                    slug=slug,
                    name=display_name,
                )
                break
            if existing.name.casefold() == display_name.casefold():
                city = existing
                break
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        TypicalPrice.objects.filter(pk=row["pk"]).update(
            city=display_name,
            city_ref_id=city.pk,
        )


def reverse_backfill_price_city_refs(apps, schema_editor):
    TypicalPrice = apps.get_model("culture", "TypicalPrice")
    TypicalPrice.objects.update(city_ref=None)


class Migration(migrations.Migration):
    dependencies = [
        ("countries", "0003_city"),
        ("culture", "0002_destination_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="typicalprice",
            name="city_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="typical_prices",
                to="countries.city",
            ),
        ),
        migrations.RunPython(
            backfill_price_city_refs,
            reverse_backfill_price_city_refs,
        ),
    ]
