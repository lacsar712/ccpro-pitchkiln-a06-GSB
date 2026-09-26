"""灶台相位切换业务规则。"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

DRAWING_SOFT_POINT_MAX = Decimal("95")

# 软化复核链门槛：复核号从 1 起连续、链长下限、相邻复核软化点绝对差上限。
RECHECK_CHAIN_MIN = 3
RECHECK_ADJACENT_MAX_DIFF = Decimal("4")


def consecutive_recheck_chain(run):
    """按复核号升序取从 1 起的连续复核段（遇缺号即截断）。"""
    chain = []
    for expected, recheck in enumerate(run.rechecks.order_by("recheckNo"), start=1):
        if recheck.recheckNo != expected:
            break
        chain.append(recheck)
    return chain


def assert_can_enter_drawing(hearth):
    """
    进入「出胶」相位前的统一门槛（相位表单与改相位入口共用此源）：

    1. 当前未收灶的 CookRun 须至少有一条 softPointC <= 95 的 SoftPointProbe；
    2. 软化复核链：复核号从 1 起连续、不少于 3 条；
    3. 链内相邻复核软化点绝对差 <= 4℃；
    4. 链首最新复核时刻须晚于最新探针时刻。

    校验通过时返回连续复核链（供改相位入口落针），否则抛 ValidationError。
    """
    open_run = hearth.open_run()
    if open_run is None:
        raise ValidationError(
            {"phase": "无法进入出胶：该灶没有进行中的值守纪录。"}
        )

    ok = open_run.probes.filter(softPointC__lte=DRAWING_SOFT_POINT_MAX).exists()
    if not ok:
        raise ValidationError(
            {
                "phase": (
                    "无法进入出胶：进行中值守尚无软化点探针 "
                    f"≤ {DRAWING_SOFT_POINT_MAX}℃。"
                )
            }
        )

    chain = consecutive_recheck_chain(open_run)
    if len(chain) < RECHECK_CHAIN_MIN:
        raise ValidationError(
            {
                "phase": (
                    "无法进入出胶：软化复核链从 1 起连续仅 "
                    f"{len(chain)} 条，需不少于 {RECHECK_CHAIN_MIN} 条。"
                )
            }
        )

    for prev, curr in zip(chain, chain[1:]):
        diff = abs(curr.softPointC - prev.softPointC)
        if diff > RECHECK_ADJACENT_MAX_DIFF:
            raise ValidationError(
                {
                    "phase": (
                        f"无法进入出胶：复核 #{prev.recheckNo} 与 #{curr.recheckNo} "
                        f"软化点相差 {diff}℃，超出相邻差限 "
                        f"{RECHECK_ADJACENT_MAX_DIFF}℃。"
                    )
                }
            )

    latest_probe = open_run.probes.order_by("-sampledAt", "-id").first()
    latest_recheck = chain[-1]
    if latest_probe is not None and latest_recheck.checkedAt <= latest_probe.sampledAt:
        raise ValidationError(
            {
                "phase": (
                    "无法进入出胶：最新复核时刻须晚于最新探针时刻"
                    f"（探针 {latest_probe.sampledAt:%Y-%m-%d %H:%M}）。"
                )
            }
        )

    return chain


def _drop_recheck_probe(recheck) -> None:
    """把最新复核软化点落一条探针，让时间线可见复核达标值。"""
    from apps.kiln.models import SoftPointProbe

    SoftPointProbe.objects.create(
        run=recheck.run,
        sampledAt=recheck.checkedAt,
        softPointC=recheck.softPointC,
        samplerName=f"复核#{recheck.recheckNo}·{recheck.checkerName}",
    )


def change_hearth_phase(hearth, new_phase: str):
    """统一入口：改相位时校验出胶规则并保存。"""
    from apps.kiln.models import FireHearth

    with transaction.atomic():
        if new_phase == FireHearth.PHASE_DRAWING:
            chain = assert_can_enter_drawing(hearth)
            _drop_recheck_probe(chain[-1])

        hearth.phase = new_phase
        hearth.save(update_fields=["phase"])
    return hearth
