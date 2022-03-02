# Generated by Django 3.2.7 on 2022-03-02 19:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('allocate', '0003_alter_pipe_allocation'),
    ]

    operations = [
        migrations.AddField(
            model_name='agfield',
            name='acres',
            field=models.DecimalField(decimal_places=4, default=0, max_digits=10),
            preserve_default=False,
        ),
    ]
