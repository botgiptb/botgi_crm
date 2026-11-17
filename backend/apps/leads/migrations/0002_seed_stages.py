from django.db import migrations


def seed_stages(apps, schema_editor):
    Stage = apps.get_model("leads", "Stage")
    stages_data = [
        {
            "name": "New",
            "slug": "new",
            "order": 0,
            "is_won": False,
            "is_lost": False,
            "color": "#3b82f6",
        },
        {
            "name": "Contacted",
            "slug": "contacted",
            "order": 1,
            "is_won": False,
            "is_lost": False,
            "color": "#eab308",
        },
        {
            "name": "Quoted",
            "slug": "quoted",
            "order": 2,
            "is_won": False,
            "is_lost": False,
            "color": "#a855f7",
        },
        {
            "name": "Follow-up",
            "slug": "follow_up",
            "order": 3,
            "is_won": False,
            "is_lost": False,
            "color": "#f97316",
        },
        {
            "name": "Won",
            "slug": "won",
            "order": 4,
            "is_won": True,
            "is_lost": False,
            "color": "#22c55e",
        },
        {
            "name": "Lost",
            "slug": "lost",
            "order": 5,
            "is_won": False,
            "is_lost": True,
            "color": "#ef4444",
        },
    ]

    for item in stages_data:
        Stage.objects.update_or_create(slug=item["slug"], defaults=item)


def reverse_seed(apps, schema_editor):
    Stage = apps.get_model("leads", "Stage")
    Stage.objects.filter(slug__in=["new", "contacted", "quoted", "follow_up", "won", "lost"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_stages, reverse_seed),
    ]
