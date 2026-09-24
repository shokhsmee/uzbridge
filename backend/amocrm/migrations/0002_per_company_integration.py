import secrets

from django.conf import settings
from django.db import migrations, models

import core.crypto


def fill_hook_tokens(apps, schema_editor):
    AmoConnection = apps.get_model("amocrm", "AmoConnection")
    for conn in AmoConnection.objects.all():
        conn.hook_token = secrets.token_urlsafe()
        conn.save(update_fields=["hook_token"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("amocrm", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="amoconnection",
            name="client_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="amoconnection",
            name="client_secret",
            field=core.crypto.EncryptedTextField(blank=True),
        ),
        migrations.AddField(
            model_name="amoconnection",
            name="link_stages",
            field=models.JSONField(blank=True, default=dict),
        ),
        # Unique with a callable default: add plain, fill one per row, then constrain.
        migrations.AddField(
            model_name="amoconnection",
            name="hook_token",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(fill_hook_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="amoconnection",
            name="hook_token",
            field=models.CharField(default=secrets.token_urlsafe, max_length=64, unique=True),
        ),
        migrations.CreateModel(
            name="AmoInstall",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nonce", models.CharField(max_length=32, unique=True)),
                ("client_id", models.CharField(blank=True, max_length=64)),
                ("client_secret", core.crypto.EncryptedTextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("company", models.ForeignKey(on_delete=models.deletion.CASCADE, to="accounts.company")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
        ),
    ]
