from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_monthlyworkspace"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="monthlyworkspace",
            name="language",
        ),
    ]
