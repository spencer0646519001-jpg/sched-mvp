from django.core.management.base import BaseCommand

from core.models import Tenant


class Command(BaseCommand):
    help = "Seed minimal demo data for local/docker demo environments."

    def handle(self, *args, **options):
        tenant_name = "demo_kitchen"
        tenant, created = Tenant.objects.get_or_create(name=tenant_name)
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created demo tenant: {tenant.name}")
            )
        else:
            self.stdout.write(f"Demo tenant already exists: {tenant.name}")
