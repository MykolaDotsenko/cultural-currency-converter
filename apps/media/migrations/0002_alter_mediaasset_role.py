from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("media", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mediaasset",
            name="role",
            field=models.CharField(
                choices=[
                    ("country_hero", "Country hero"),
                    ("country_teaser", "Country teaser"),
                    ("everyday_value", "Everyday value"),
                    ("payment_culture", "Payment culture"),
                    ("local_detail", "Local detail"),
                    ("story_cover", "Story cover"),
                    ("story_chapter", "Story chapter"),
                    ("comparison_then", "Comparison then"),
                    ("comparison_now", "Comparison now"),
                    ("historical_timeline", "Historical timeline"),
                    ("social_preview", "Social preview"),
                    ("decorative_background", "Decorative background"),
                ],
                max_length=32,
            ),
        ),
    ]
