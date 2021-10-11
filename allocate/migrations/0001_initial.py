# Generated by Django 3.2.7 on 2021-10-11 00:56

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Crop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vw_crop_name', models.TextField(unique=True)),
                ('ucm_group', models.TextField(null=True)),
                ('liq_crop_name', models.TextField(null=True)),
                ('liq_crop_id', models.CharField(max_length=5, null=True)),
                ('liq_group_code', models.CharField(max_length=5, null=True)),
                ('liq_group_name', models.TextField(null=True)),
                ('_efficiency_options', models.TextField(null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Well',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('well_id', models.TextField(unique=True)),
                ('apn', models.TextField()),
                ('ucm_service_area_id', models.TextField()),
                ('allocated_amount', models.DecimalField(decimal_places=4, max_digits=16, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='WellProduction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.SmallIntegerField()),
                ('month', models.SmallIntegerField()),
                ('semi_year', models.SmallIntegerField()),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=16)),
                ('crop', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='production', to='allocate.crop')),
                ('well', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='production', to='allocate.well')),
            ],
        ),
        migrations.CreateModel(
            name='AgField',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ucm_service_area_id', models.TextField()),
                ('liq_id', models.TextField(unique=True)),
                ('openet_id', models.TextField(null=True)),
                ('crop', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='allocate.crop')),
            ],
        ),
        migrations.CreateModel(
            name='Pipe',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('distance', models.DecimalField(decimal_places=4, max_digits=16)),
                ('variable_name', models.TextField(null=True)),
                ('allocation', models.DecimalField(decimal_places=4, max_digits=16)),
                ('agfield', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pipes', to='allocate.agfield')),
                ('well', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pipes', to='allocate.well')),
            ],
            options={
                'unique_together': {('well', 'agfield')},
            },
        ),
        migrations.CreateModel(
            name='AgFieldTimestep',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestep', models.SmallIntegerField()),
                ('consumptive_use', models.DecimalField(decimal_places=4, max_digits=16)),
                ('precip', models.DecimalField(decimal_places=4, max_digits=16)),
                ('agfield', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='timesteps', to='allocate.agfield')),
            ],
            options={
                'unique_together': {('agfield', 'timestep')},
            },
        ),
    ]