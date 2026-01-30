from django.contrib import admin
from .models import Tenant, Station, Employee, EmployeeStationSkill

admin.site.register(Tenant)
admin.site.register(Station)
admin.site.register(Employee)
admin.site.register(EmployeeStationSkill)
