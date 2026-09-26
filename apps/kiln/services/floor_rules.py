"""灶台相位切换业务规则。"""
from decimal import Decimal

from django.core.exceptions import ValidationError

DRAWING_SOFT_POINT_MAX = Decimal("95")
RECHECK_CHAIN_MIN = 3
RECHECK_STEP_MAX_DELTA = Decimal("4")


def recheck_chain_status(run):
    """
    汇总值守的软化复核链状态（全站唯一出处）：
    - chain: 从 1 起连续编号的复核（按复核号升序），遇断号即止；
    - latest: 该值守时刻最新的一条复核（无复核时为 None）。
    """
    rechecks = list(run.rechecks.order_by("recheckNo", "id"))
    chain = []
    expect = 1
    for r in rechecks:
        if r.recheckNo == expect:
            chain.append(r)
            expect += 1
        elif r.recheckNo > expect:
            break
    latest = max(rechecks, key=lambda r: (r.checkedAt, r.id), default=None)
    return chain, latest


def assert_can_enter_drawing(hearth) -> None:
    """
    进入「出胶」相位前的双重门槛：
    1. 探针门槛：当前未收灶的 CookRun 须至少有一条
       softPointC <= 95 的 SoftPointProbe；
    2. 软化复核链：从 1 起连续编号不少于 3 条、链内相邻复核
       软化点绝对差不大于 4℃、最新复核时刻晚于最新探针时刻。
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

    chain, latest = recheck_chain_status(open_run)
    if len(chain) < RECHECK_CHAIN_MIN:
        raise ValidationError(
            {
                "phase": (
                    "无法进入出胶：软化复核链未齐 — 须从 1 起连续编号满 "
                    f"{RECHECK_CHAIN_MIN} 条（当前连续 {len(chain)} 条）。"
                )
            }
        )
    for prev, curr in zip(chain, chain[1:]):
        delta = abs(curr.softPointC - prev.softPointC)
        if delta > RECHECK_STEP_MAX_DELTA:
            raise ValidationError(
                {
                    "phase": (
                        "无法进入出胶：复核 "
                        f"#{prev.recheckNo}→#{curr.recheckNo} 软化点差 "
                        f"{delta}℃ 超出限值 {RECHECK_STEP_MAX_DELTA}℃。"
                    )
                }
            )
    latest_probe = open_run.probes.order_by("-sampledAt", "-id").first()
    if (
        latest is None
        or latest_probe is None
        or latest.checkedAt <= latest_probe.sampledAt
    ):
        raise ValidationError(
            {"phase": "无法进入出胶：最新复核时刻须晚于最新探针时刻。"}
        )


def record_recheck_probe(hearth):
    """出胶放行后：把最新复核软化点落一条探针，供时间线可见。"""
    from apps.kiln.models import SoftPointProbe

    open_run = hearth.open_run()
    if open_run is None:
        return None
    _, latest = recheck_chain_status(open_run)
    if latest is None:
        return None
    return SoftPointProbe.objects.create(
        run=open_run,
        sampledAt=latest.checkedAt,
        softPointC=latest.softPointC,
        samplerName=f"{latest.checkerName}·复核#{latest.recheckNo}",
    )


def change_hearth_phase(hearth, new_phase: str):
    """统一入口：改相位时校验出胶规则并保存；放行出胶后落复核探针。"""
    from apps.kiln.models import FireHearth

    entering_drawing = new_phase == FireHearth.PHASE_DRAWING
    if entering_drawing:
        assert_can_enter_drawing(hearth)

    hearth.phase = new_phase
    hearth.save(update_fields=["phase"])

    if entering_drawing:
        record_recheck_probe(hearth)
    return hearth
