import pytest
from apps.leads.models import Stage


@pytest.fixture(autouse=True)
def seed_test_stages(db):
    """Ensure standard pipeline stages exist in the test database."""
    stages = [
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
    for st in stages:
        Stage.objects.get_or_create(slug=st["slug"], defaults=st)
