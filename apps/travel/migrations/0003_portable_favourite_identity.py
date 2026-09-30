from django.db import migrations, models
from django.db.models import Q


def remove_duplicate_favourites(apps, schema_editor):
    FavouritePair = apps.get_model("travel", "FavouritePair")
    seen = set()
    duplicate_ids = []

    favourites = FavouritePair.objects.order_by(
        "user_id",
        "source_currency_id",
        "destination_currency_id",
        "source_country_id",
        "destination_country_id",
        "-updated_at",
        "-id",
    )
    for favourite in favourites.iterator():
        identity = (
            favourite.user_id,
            favourite.source_currency_id,
            favourite.destination_currency_id,
            favourite.source_country_id,
            favourite.destination_country_id,
        )
        if identity in seen:
            duplicate_ids.append(favourite.pk)
        else:
            seen.add(identity)

    if duplicate_ids:
        FavouritePair.objects.filter(pk__in=duplicate_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("travel", "0002_recent_conversion"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="favouritepair",
            name="unique_user_favourite_pair",
        ),
        migrations.RunPython(
            remove_duplicate_favourites,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="favouritepair",
            constraint=models.UniqueConstraint(
                fields=("user", "source_currency", "destination_currency"),
                condition=Q(
                    source_country__isnull=True,
                    destination_country__isnull=True,
                ),
                name="unique_fav_no_countries",
            ),
        ),
        migrations.AddConstraint(
            model_name="favouritepair",
            constraint=models.UniqueConstraint(
                fields=(
                    "user",
                    "source_currency",
                    "destination_currency",
                    "destination_country",
                ),
                condition=Q(
                    source_country__isnull=True,
                    destination_country__isnull=False,
                ),
                name="unique_fav_destination_country",
            ),
        ),
        migrations.AddConstraint(
            model_name="favouritepair",
            constraint=models.UniqueConstraint(
                fields=(
                    "user",
                    "source_currency",
                    "destination_currency",
                    "source_country",
                ),
                condition=Q(
                    source_country__isnull=False,
                    destination_country__isnull=True,
                ),
                name="unique_fav_source_country",
            ),
        ),
        migrations.AddConstraint(
            model_name="favouritepair",
            constraint=models.UniqueConstraint(
                fields=(
                    "user",
                    "source_currency",
                    "destination_currency",
                    "source_country",
                    "destination_country",
                ),
                condition=Q(
                    source_country__isnull=False,
                    destination_country__isnull=False,
                ),
                name="unique_fav_both_countries",
            ),
        ),
    ]
