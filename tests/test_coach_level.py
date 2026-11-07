import pytest

from runai.coach import (
    CoachProfile,
    Goal,
    Level,
    RecentRace,
    RecentRun,
    assess,
    trail_time_range,
)
from runai.coach.level import cooper_vo2max, riegel, time_from_vdot
from runai.coach.models import DISTANCES_KM
from runai.models import RunnerProfile

# Tables publiées de Daniels (Daniels' Running Formula) : VDOT -> 5k, 10k, semi, marathon (s).
DANIELS_TABLE = {
    40: (24 * 60 + 8, 50 * 60 + 3, 1 * 3600 + 50 * 60 + 59, 3 * 3600 + 49 * 60 + 45),
    50: (19 * 60 + 57, 41 * 60 + 21, 1 * 3600 + 31 * 60 + 35, 3 * 3600 + 10 * 60 + 49),
    60: (17 * 60 + 3, 35 * 60 + 22, 1 * 3600 + 18 * 60 + 9, 2 * 3600 + 43 * 60 + 25),
}


@pytest.mark.parametrize("vdot", DANIELS_TABLE)
def test_daniels_implementation_matches_published_table(vdot):
    for km, expected in zip(DISTANCES_KM.values(), DANIELS_TABLE[vdot], strict=True):
        assert time_from_vdot(km, vdot) == pytest.approx(expected, rel=0.005)


def test_riegel_and_cooper_formulas():
    assert riegel(50 * 60, 10, 21.0975) == pytest.approx(6619, abs=2)
    assert cooper_vo2max(2800) == pytest.approx(51.3, abs=0.1)


def test_coach_profile_is_not_the_identity_profile():
    assert CoachProfile is not RunnerProfile
    assert not set(CoachProfile.model_fields) & {"first_name", "last_name", "email"}


def assert_ranges_are_sane(result):
    previous = 0
    for name in DISTANCES_KM:
        r = result.estimate.predictions[name]
        assert previous < r.low_s < r.high_s
        previous = r.low_s


def test_profile_1_beginner_without_any_time():
    p = CoachProfile(sessions_per_week=2, longest_recent_run=RecentRun(distance_km=5), running_since_months=3, goals=[Goal.premier_10k])
    r = assess(p, weeks_available=8)
    assert_ranges_are_sane(r)
    assert r.estimate.source == "declaratif" and r.estimate.confidence == "basse"
    assert r.estimate.level == Level.debutant
    ten = r.estimate.predictions["10k"]
    assert 55 * 60 < ten.low_s and ten.high_s > 70 * 60
    assert r.advice_for("10k").verdict in ("recommande", "possible")
    assert r.advice_for("marathon").verdict == "bloque"
    assert r.advice_for("semi").verdict in ("bloque", "deconseille")
    assert "marathon" in r.not_advised


def test_profile_2_beginner_marathon_in_six_weeks_is_blocked():
    p = CoachProfile(sessions_per_week=2, weekly_km=12, recent_race=RecentRace(distance_km=10, time_s=65 * 60, months_ago=1), longest_recent_run=RecentRun(distance_km=8))
    r = assess(p, weeks_available=6)
    assert r.estimate.level == Level.debutant
    assert r.advice_for("marathon").verdict == "bloque"
    assert "6 semaines" in r.advice_for("marathon").reason
    assert r.advice_for("semi").verdict == "bloque"
    assert r.advice_for("10k").verdict in ("recommande", "possible")


def test_profile_3_intermediate_recent_10k():
    p = CoachProfile(sessions_per_week=3, weekly_km=30, recent_race=RecentRace(distance_km=10, time_s=50 * 60, months_ago=2), longest_recent_run=RecentRun(distance_km=14, duration_min=85))
    r = assess(p, weeks_available=12)
    assert_ranges_are_sane(r)
    assert r.estimate.source == "chrono" and r.estimate.confidence == "haute"
    assert r.estimate.level == Level.intermediaire
    semi = r.estimate.predictions["semi"]
    assert semi.low_s <= riegel(3000, 10, 21.0975) <= semi.high_s
    assert 1 * 3600 + 48 * 60 < semi.low_s and semi.high_s < 2 * 3600 + 5 * 60
    marathon = r.estimate.predictions["marathon"]
    assert marathon.high_s - marathon.low_s > 20 * 60
    assert r.advice_for("semi").verdict == "recommande"
    assert r.advice_for("marathon").verdict == "deconseille"
    assert "semi" in r.recommended and "Niveau intermédiaire" in r.summary()


def test_profile_4_confirmed_half_marathon():
    p = CoachProfile(sessions_per_week=5, weekly_km=60, recent_race=RecentRace(distance_km=21.0975, time_s=90 * 60, months_ago=3), longest_recent_run=RecentRun(distance_km=24, duration_min=125))
    r = assess(p, weeks_available=16)
    assert_ranges_are_sane(r)
    assert r.estimate.level == Level.confirme
    marathon = r.estimate.predictions["marathon"]
    assert 3 * 3600 + 3 * 60 < marathon.low_s < 3 * 3600 + 12 * 60
    assert 3 * 3600 + 15 * 60 < marathon.high_s < 3 * 3600 + 35 * 60
    assert r.advice_for("marathon").verdict == "recommande"


def test_profile_5_training_run_only():
    p = CoachProfile(sessions_per_week=3, longest_recent_run=RecentRun(distance_km=12, duration_min=70), goals=[Goal.voyage])
    r = assess(p, weeks_available=10)
    assert_ranges_are_sane(r)
    assert r.estimate.source == "sortie" and r.estimate.confidence == "moyenne"
    ten = r.estimate.predictions["10k"]
    assert ten.low_s < 58 * 60 * 0.97 and ten.high_s > 55 * 60
    assert r.advice_for("10k").verdict == "recommande"


def test_profile_6_cooper_test():
    r = assess(CoachProfile(sessions_per_week=4, weekly_km=35, cooper_m=2800))
    assert_ranges_are_sane(r)
    assert r.estimate.source == "test_cooper"
    assert r.estimate.vdot_low < 44 and r.estimate.vdot_high >= 51
    assert r.estimate.level in (Level.intermediaire, Level.confirme)
    assert all(a.verdict == "possible" for a in r.advice)


def test_profile_7_expert():
    p = CoachProfile(sessions_per_week=7, weekly_km=90, recent_race=RecentRace(distance_km=10, time_s=34 * 60, months_ago=1), longest_recent_run=RecentRun(distance_km=28))
    r = assess(p, weeks_available=12)
    assert r.estimate.level == Level.expert
    marathon = r.estimate.predictions["marathon"]
    assert 2 * 3600 + 30 * 60 < marathon.low_s < 2 * 3600 + 40 * 60
    assert marathon.high_s < 2 * 3600 + 55 * 60
    assert r.advice_for("marathon").verdict in ("recommande", "possible")


def test_profile_8_senior_old_time_and_trail():
    fresh = CoachProfile(sessions_per_week=4, weekly_km=40, age=62, recent_race=RecentRace(distance_km=42.195, time_s=225 * 60, months_ago=0), goals=[Goal.trail])
    old = fresh.model_copy(update={"recent_race": RecentRace(distance_km=42.195, time_s=225 * 60, months_ago=18)})
    r_fresh, r_old = assess(fresh, 20), assess(old, 20)
    assert r_old.estimate.confidence == "moyenne" and r_old.estimate.notes

    def width(r):
        return r.estimate.predictions["10k"].high_s - r.estimate.predictions["10k"].low_s

    assert width(r_old) > width(r_fresh)
    trail = trail_time_range(old, 20, 800)
    assert trail.low_s > r_old.estimate.predictions["semi"].low_s
    assert trail.high_s < 5 * 3600


def test_marathon_needs_three_sessions_a_week():
    p = CoachProfile(sessions_per_week=2, weekly_km=30, recent_race=RecentRace(distance_km=21.0975, time_s=6600, months_ago=2), longest_recent_run=RecentRun(distance_km=20))
    assert assess(p, weeks_available=30).advice_for("marathon").verdict == "deconseille"


def test_teenager_distance_cap():
    p = CoachProfile(sessions_per_week=3, weekly_km=25, age=15, recent_race=RecentRace(distance_km=10, time_s=45 * 60, months_ago=1))
    r = assess(p, weeks_available=30)
    assert r.advice_for("semi").verdict == "bloque" and r.advice_for("marathon").verdict == "bloque"
