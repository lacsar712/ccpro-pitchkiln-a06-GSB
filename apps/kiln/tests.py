"""软化复核链与出胶门槛的规则测试。"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from .forms import PhaseChangeForm, SoftPointRecheckForm
from .models import CookRun, FireHearth, ResinLot, SoftPointProbe, SoftPointRecheck
from .services.floor_rules import (
    RECHECK_CHAIN_MIN,
    RECHECK_STEP_MAX_DELTA,
    assert_can_enter_drawing,
    change_hearth_phase,
)


def _make_hearth_with_run(**run_kwargs):
    lot = ResinLot.objects.create(
        lotCode="脂-测试-0001",
        originPlace="松脂坳",
        arrivalKg=Decimal("100.00"),
        receivedAt=timezone.now(),
    )
    hearth = FireHearth.objects.create(
        lane=1,
        tag="测火-甲",
        resinGrade="特级脂",
        phase=FireHearth.PHASE_HOLDING,
    )
    run = CookRun.objects.create(
        hearth=hearth,
        resinLot=lot,
        openedAt=timezone.now() - timezone.timedelta(hours=5),
        targetSoftPointC=Decimal("88.00"),
        **run_kwargs,
    )
    return hearth, run


def _probe(run, hours_ago, point):
    return SoftPointProbe.objects.create(
        run=run,
        sampledAt=timezone.now() - timezone.timedelta(hours=hours_ago),
        softPointC=Decimal(str(point)),
        samplerName="值守测试",
    )


def _recheck(run, no, hours_ago, point):
    return SoftPointRecheck.objects.create(
        run=run,
        recheckNo=no,
        checkedAt=timezone.now() - timezone.timedelta(hours=hours_ago),
        softPointC=Decimal(str(point)),
        checkerName="复核测试",
    )


def _good_run():
    """探针达标 + 三条连续复核、相邻差 ≤4、最新复核晚于最新探针。"""
    hearth, run = _make_hearth_with_run()
    _probe(run, 3, "94.00")
    _recheck(run, 1, 2.5, "93.50")
    _recheck(run, 2, 2, "92.00")
    _recheck(run, 3, 1, "90.50")
    return hearth, run


class DrawingGateTests(TestCase):
    def test_probe_threshold_still_blocks(self):
        hearth, run = _make_hearth_with_run()
        _probe(run, 1, "96.00")
        _recheck(run, 1, 0.8, "94.00")
        _recheck(run, 2, 0.6, "93.00")
        _recheck(run, 3, 0.4, "92.00")
        with self.assertRaises(ValidationError):
            assert_can_enter_drawing(hearth)

    def test_no_open_run_blocks(self):
        hearth, _ = _make_hearth_with_run(
            closedAt=timezone.now() - timezone.timedelta(hours=1)
        )
        with self.assertRaises(ValidationError):
            assert_can_enter_drawing(hearth)

    def test_chain_too_short_blocks(self):
        hearth, run = _make_hearth_with_run()
        _probe(run, 2, "94.00")
        _recheck(run, 1, 1.5, "93.00")
        _recheck(run, 2, 1, "92.50")
        with self.assertRaises(ValidationError) as ctx:
            assert_can_enter_drawing(hearth)
        self.assertIn("复核链未齐", str(ctx.exception))

    def test_chain_gap_blocks(self):
        hearth, run = _make_hearth_with_run()
        _probe(run, 3, "94.00")
        _recheck(run, 1, 2.5, "93.00")
        _recheck(run, 2, 2, "92.50")
        _recheck(run, 4, 1, "92.00")  # 断号：缺 #3
        with self.assertRaises(ValidationError) as ctx:
            assert_can_enter_drawing(hearth)
        self.assertIn("复核链未齐", str(ctx.exception))

    def test_adjacent_delta_over_limit_blocks(self):
        hearth, run = _make_hearth_with_run()
        _probe(run, 3, "94.00")
        _recheck(run, 1, 2.5, "93.00")
        _recheck(run, 2, 2, "92.50")
        # 与 #2 相邻差 4.1℃ > 限值 4℃
        _recheck(run, 3, 1, str(Decimal("92.50") + RECHECK_STEP_MAX_DELTA + Decimal("0.1")))
        with self.assertRaises(ValidationError) as ctx:
            assert_can_enter_drawing(hearth)
        self.assertIn("超出限值", str(ctx.exception))

    def test_stale_recheck_blocks(self):
        hearth, run = _make_hearth_with_run()
        _recheck(run, 1, 3, "93.50")
        _recheck(run, 2, 2.5, "92.50")
        _recheck(run, 3, 2, "92.00")
        _probe(run, 1, "94.00")  # 最新探针晚于最新复核
        with self.assertRaises(ValidationError) as ctx:
            assert_can_enter_drawing(hearth)
        self.assertIn("晚于最新探针", str(ctx.exception))

    def test_full_chain_passes_and_drops_probe(self):
        hearth, run = _good_run()
        assert_can_enter_drawing(hearth)  # 不抛异常
        before = run.probes.count()
        change_hearth_phase(hearth, FireHearth.PHASE_DRAWING)
        hearth.refresh_from_db()
        self.assertEqual(hearth.phase, FireHearth.PHASE_DRAWING)
        self.assertEqual(run.probes.count(), before + 1)
        dropped = run.probes.order_by("-id").first()
        latest = run.rechecks.order_by("-checkedAt", "-id").first()
        self.assertEqual(dropped.softPointC, latest.softPointC)
        self.assertEqual(dropped.sampledAt, latest.checkedAt)
        self.assertIn("复核#3", dropped.samplerName)

    def test_blocked_chain_keeps_phase_and_no_probe(self):
        hearth, run = _make_hearth_with_run()
        _probe(run, 2, "94.00")
        _recheck(run, 1, 1, "93.00")
        before = run.probes.count()
        with self.assertRaises(ValidationError):
            change_hearth_phase(hearth, FireHearth.PHASE_DRAWING)
        hearth.refresh_from_db()
        self.assertNotEqual(hearth.phase, FireHearth.PHASE_DRAWING)
        self.assertEqual(run.probes.count(), before)

    def test_form_and_entry_share_same_rules(self):
        """复核达标逻辑与改相位入口同源：表单与服务拦同一缺口。"""
        hearth, run = _make_hearth_with_run()
        _probe(run, 2, "94.00")
        _recheck(run, 1, 1, "93.00")  # 链未满三条
        form = PhaseChangeForm(
            data={"phase": FireHearth.PHASE_DRAWING}, hearth=hearth
        )
        self.assertFalse(form.is_valid())
        self.assertIn("复核链未齐", str(form.errors))
        with self.assertRaises(ValidationError):
            change_hearth_phase(hearth, FireHearth.PHASE_DRAWING)


class RecheckRegistrationTests(TestCase):
    def test_unique_recheck_no_per_run_db(self):
        _, run = _make_hearth_with_run()
        _recheck(run, 1, 1, "93.00")
        with self.assertRaises(IntegrityError):
            _recheck(run, 1, 0.5, "92.00")

    def test_closed_run_rejects_recheck_form(self):
        _, run = _make_hearth_with_run(
            closedAt=timezone.now() - timezone.timedelta(minutes=5)
        )
        form = SoftPointRecheckForm(
            data={
                "recheckNo": 1,
                "checkedAt": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "softPointC": "93.00",
                "checkerName": "复核测试",
            },
            run=run,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("已收灶", str(form.errors))

    def test_duplicate_recheck_no_rejected_by_form(self):
        _, run = _make_hearth_with_run()
        _recheck(run, 1, 1, "93.00")
        form = SoftPointRecheckForm(
            data={
                "recheckNo": 1,
                "checkedAt": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "softPointC": "92.00",
                "checkerName": "复核测试",
            },
            run=run,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("唯一", str(form.errors))

    def test_recheck_no_must_start_from_one(self):
        _, run = _make_hearth_with_run()
        form = SoftPointRecheckForm(
            data={
                "recheckNo": 0,
                "checkedAt": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "softPointC": "93.00",
                "checkerName": "复核测试",
            },
            run=run,
        )
        self.assertFalse(form.is_valid())

    def test_open_run_accepts_recheck(self):
        _, run = _make_hearth_with_run()
        form = SoftPointRecheckForm(
            data={
                "recheckNo": 1,
                "checkedAt": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "softPointC": "93.00",
                "checkerName": "复核测试",
            },
            run=run,
        )
        self.assertTrue(form.is_valid(), form.errors)
        recheck = form.save(commit=False)
        recheck.run = run
        recheck.save()
        self.assertEqual(run.rechecks.count(), 1)


class RecheckChainConstantsTests(TestCase):
    def test_chain_min_and_delta_limit(self):
        self.assertEqual(RECHECK_CHAIN_MIN, 3)
        self.assertEqual(RECHECK_STEP_MAX_DELTA, Decimal("4"))
