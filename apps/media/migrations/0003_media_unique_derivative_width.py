from django.db import migrations, models
from django.db.models import Count, Q


def assert_unique_derivative_widths(apps, schema_editor):
    MediaAsset = apps.get_model("media", "MediaAsset")
    duplicate = (
        MediaAsset.objects.filter(
            derivative_of__isnull=False,
            variant_width__isnull=False,
        )
        .values("derivative_of_id", "variant_width")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .order_by("derivative_of_id", "variant_width")
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot add media_unique_derivative_width: duplicate responsive derivatives "
            f"exist for source={duplicate['derivative_of_id']} "
            f"width={duplicate['variant_width']}. Resolve the records explicitly and rerun."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("media", "0002_alter_mediaasset_role"),
    ]

    operations = [
        migrations.RunPython(
            assert_unique_derivative_widths,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="mediaasset",
            constraint=models.UniqueConstraint(
                fields=("derivative_of", "variant_width"),
                condition=Q(derivative_of__isnull=False, variant_width__isnull=False),
                name="media_unique_derivative_width",
            ),
        ),
    ]
