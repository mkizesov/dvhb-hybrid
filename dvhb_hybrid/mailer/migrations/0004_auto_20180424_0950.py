# Generated by Django 2.0.1 on 2018-04-24 09:50

from django.db import migrations, models
import dvhb_hybrid.mailer.models


class Migration(migrations.Migration):

    dependencies = [
        ('mailer', '0003_auto_20171213_0805'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='html',
            field=models.TextField(null=True),
        ),
        migrations.AddField(
            model_name='templatetranslation',
            name='file_html',
            field=models.FileField(blank=True, null=True, upload_to=dvhb_hybrid.mailer.models.template_target, validators=[dvhb_hybrid.mailer.models.validate_file_extension], verbose_name='html'),
        ),
    ]