from django.contrib import admin

from .models import CookRun, FireHearth, ResinLot, SoftPointProbe, SoftPointRecheck


@admin.register(ResinLot)
class ResinLotAdmin(admin.ModelAdmin):
    list_display = ("id", "lotCode", "originPlace", "arrivalKg", "receivedAt")
    search_fields = ("lotCode", "originPlace")


@admin.register(FireHearth)
class FireHearthAdmin(admin.ModelAdmin):
    list_display = ("id", "lane", "tag", "resinGrade", "phase")
    list_filter = ("phase", "lane")
    search_fields = ("tag", "resinGrade")


@admin.register(CookRun)
class CookRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "hearth",
        "resinLot",
        "openedAt",
        "closedAt",
        "targetSoftPointC",
    )
    list_filter = ("hearth",)
    search_fields = ("hearth__tag", "resinLot__lotCode")


@admin.register(SoftPointProbe)
class SoftPointProbeAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "sampledAt", "softPointC", "samplerName")
    search_fields = ("samplerName",)


@admin.register(SoftPointRecheck)
class SoftPointRecheckAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "recheckNo", "softPointC", "checkedAt", "checkerName")
    list_filter = ("run__hearth",)
    search_fields = ("checkerName", "run__hearth__tag")
