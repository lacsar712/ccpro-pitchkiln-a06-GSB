# Generated manually for PitchKiln-01 softening recheck chain

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kiln", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SoftPointRecheck",
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
                    "recheckNo",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="复核号",
                    ),
                ),
                (
                    "softPointC",
                    models.DecimalField(
                        decimal_places=2, max_digits=6, verbose_name="复核软化点(℃)"
                    ),
                ),
                ("checkedAt", models.DateTimeField(verbose_name="复核时刻")),
                (
                    "checkerName",
                    models.CharField(max_length=80, verbose_name="复核人"),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rechecks",
                        to="kiln.cookrun",
                        verbose_name="值守",
                    ),
                ),
            ],
            options={
                "verbose_name": "软化复核",
                "verbose_name_plural": "软化复核",
                "ordering": ["-checkedAt", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="softpointrecheck",
            constraint=models.UniqueConstraint(
                fields=("run", "recheckNo"),
                name="uniq_recheck_no_per_run",
                violation_error_message="同一值守的复核号必须唯一。",
            ),
        ),
    ]
