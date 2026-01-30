# core/models.py
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Tenant(TimeStampedModel):
    """
    一個 Tenant = 一個廚房/店家/品牌單位（資料隔離邊界）
    """

    name = models.CharField(max_length=120, unique=True)

    def __str__(self) -> str:
        return self.name


class Station(TimeStampedModel):
    """
    站位：必須 tenant-scoped（每個店家自己的站位命名）
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="stations"
    )
    code = models.SlugField(max_length=64)  # 程式用：例如 "gateau" / "hot_kitchen"
    display_name = models.CharField(max_length=120)  # 人看的：例如 "Gateau" / "熱廚"
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("tenant", "code")]
        indexes = [
            models.Index(fields=["tenant", "code"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant}:{self.code}"


class Employee(TimeStampedModel):
    """
    員工：也必須 tenant-scoped
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="employees"
    )
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    is_assignable = models.BooleanField(default=True)
    role = models.CharField(
        max_length=20,
        choices=[("chef", "Chef"), ("staff", "Staff")],
        default="staff",
    )
    class Meta:
        unique_together = [("tenant", "name")]
        indexes = [
            models.Index(fields=["tenant", "name"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.tenant}:{self.name}"


class EmployeeStationSkill(TimeStampedModel):
    """
    員工能力矩陣：某員工會哪些 station（之後 engine / rules 會用到）
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="skills")
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="station_skills"
    )
    station = models.ForeignKey(
        Station, on_delete=models.CASCADE, related_name="employee_skills"
    )

    level = models.PositiveSmallIntegerField(default=1)  # 1~5，先保留
    can_lead = models.BooleanField(default=False)

    class Meta:
        unique_together = [("tenant", "employee", "station")]
        indexes = [
            models.Index(fields=["tenant", "station"]),
            models.Index(fields=["tenant", "employee"]),
        ]


class ScheduleRun(TimeStampedModel):
    """
    一次「排班運算」的紀錄（可追溯、可比對、可回滾）
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="schedule_runs"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    algorithm_version = models.CharField(max_length=50, default="engine_v1")
    meta = models.JSONField(
        default=dict, blank=True
    )  # 參數、權重、seed、warnings 摘要等

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "start_date"]),
            models.Index(fields=["tenant", "end_date"]),
        ]


class Assignment(TimeStampedModel):
    """
    排班結果：某天、某站位、派到誰
    """

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="assignments"
    )
    schedule_run = models.ForeignKey(
        ScheduleRun, on_delete=models.CASCADE, related_name="assignments"
    )

    date = models.DateField()
    station = models.ForeignKey(
        Station, on_delete=models.PROTECT, related_name="assignments"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="assignments"
    )

    shift_code = models.CharField(
        max_length=16
    )  # "1" / "2" / "C" 先用字串，之後再表格化
    notes = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "date", "station", "employee"],
                name="uniq_assignment_per_employee_station_day",
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "date"]),
            models.Index(fields=["tenant", "station", "date"]),
        ]
