from django.core.management.base import BaseCommand

from app.infra.engine_input_resolver import DEMO_TENANT_NAME
from core.demo_seed import ensure_demo_seed_data


class Command(BaseCommand):
    help = "Seed minimal demo data for local/docker demo environments."

    def handle(self, *args, **options):
        summary = ensure_demo_seed_data()
        if summary.tenant_created:
            self.stdout.write(self.style.SUCCESS(f"Created demo tenant: {DEMO_TENANT_NAME}"))
        else:
            self.stdout.write(f"Demo tenant already exists: {DEMO_TENANT_NAME}")

        self.stdout.write(
            "Demo persistence fixtures ready: "
            f"{summary.stations_created} station(s) created, "
            f"{summary.employees_created} employee(s) created."
        )
