from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_budget_preset"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountpreferences",
            name="preferred_language",
            field=models.CharField(
                choices=[
                    ("en", "English"),
                    ("fi", "Finnish"),
                    ("uk", "Ukrainian"),
                ],
                default="en",
                max_length=5,
            ),
        ),
        migrations.AddField(
            model_name="accountpreferences",
            name="answer_detail",
            field=models.CharField(
                choices=[
                    ("concise", "Concise"),
                    ("balanced", "Balanced"),
                    ("detailed", "Detailed"),
                ],
                default="balanced",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="accountpreferences",
            name="travel_style",
            field=models.CharField(
                choices=[
                    ("balanced", "Balanced"),
                    ("budget", "Budget-conscious"),
                    ("comfort", "Comfort-first"),
                ],
                default="balanced",
                max_length=16,
            ),
        ),
    ]
