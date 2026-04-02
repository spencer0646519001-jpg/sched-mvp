from django.contrib import admin

from .models import Employee, EmployeeStationSkill, ShiftDefinition, Station, Tenant

admin.site.register(Tenant)
admin.site.register(Station)
admin.site.register(Employee)
admin.site.register(EmployeeStationSkill)
admin.site.register(ShiftDefinition)
