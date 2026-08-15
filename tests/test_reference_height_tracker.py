"""
Tests for the ReferenceHeightTracker re-baselining behavior.

Note: sys.path is extended with BOTH src/ and src/flowguard so that
`flowguard.blockage_detector` (which does `from config import ...`) imports
cleanly, mirroring how the module is imported in the dashboard/serial_reader.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'flowguard'))

from flowguard.blockage_detector import ReferenceHeightTracker


def test_startup_clear_passage_is_unchanged():
    """Startup: fixed height set from first reading; hovering at it is normal."""
    tracker = ReferenceHeightTracker()  # no explicit initial height
    assert tracker.update(3.1) is None
    assert tracker.fixed_height == 3.1
    assert not tracker.decrease_detected
    assert tracker.update(3.2) is None
    assert tracker.fixed_height == 3.1


def test_blockage_does_not_retrigger_baseline():
    """A rise in water level (blockage) must not re-baseline the reference."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    assert tracker.update(21.5) is None
    assert tracker.fixed_height == 20.0
    assert not tracker.decrease_detected


def test_decrease_detected_immediately():
    """Requirement 1: water dropping below the reference is detected at once."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.8)
    assert tracker.decrease_detected
    assert tracker.fixed_height == 20.0  # not yet re-baselined


def test_small_decrease_stable_7_readings_updates_fixed_height():
    """Requirement 2: 7 consecutive readings within +/-5 mm -> new reference."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.8)  # decrease detected, stable streak = 1

    # 6 more readings within +/-5 mm of 18.8 -> the 7th confirms.
    events = [tracker.update(18.9) for _ in range(6)]
    assert events[:-1] == [None] * 5
    assert events[-1] == "STABLE_LEVEL_CONFIRMED"
    assert abs(tracker.fixed_height - 18.8) < 1e-9
    assert not tracker.decrease_detected


def test_stable_but_noisy_readings_never_confirm():
    """Readings bouncing outside +/-5 mm must not accept a new reference."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.8)
    noisy = [19.3, 18.1, 19.4, 18.2, 19.3, 18.1, 19.4, 18.2, 19.3]
    events = [tracker.update(h) for h in noisy]
    assert all(e is None for e in events)
    assert tracker.fixed_height == 20.0


def test_decrease_that_reverts_aborts_rebaseline():
    """If water returns to the reference, the decrease is not confirmed."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.8)
    assert tracker.decrease_detected
    assert tracker.update(19.7) is None  # back within tolerance of reference
    assert not tracker.decrease_detected
    assert tracker.fixed_height == 20.0


def test_large_decrease_5_consecutive_readings():
    """Requirement 3: >1.5 cm drop held for 5 consecutive readings updates
    fixed height = previous fixed - confirmed decrease."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    events = [tracker.update(18.2) for _ in range(5)]
    assert events[-1] == "LARGE_DECREASE_CONFIRMED"
    assert abs(tracker.fixed_height - 18.2) < 1e-9
    assert not tracker.decrease_detected


def test_large_decrease_needs_consecutive_readings():
    """A reading back above the large-decrease band resets its consecutive count."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.2)  # large count = 1
    tracker.update(18.2)  # large count = 2
    tracker.update(19.0)  # only 1.0 cm below previous fixed -> large count reset
    tracker.update(18.2)  # large count = 1 (restart)
    tracker.update(18.2)  # large count = 2
    tracker.update(18.2)  # large count = 3
    tracker.update(18.2)  # large count = 4
    events = [tracker.update(18.2)]  # large count = 5 -> confirms (stable only at 5)
    assert events[-1] == "LARGE_DECREASE_CONFIRMED"
    assert abs(tracker.fixed_height - 18.2) < 1e-9


def test_normal_calculations_continue_using_new_height():
    """After re-baselining, later readings are judged against the new fixed height."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    tracker.update(18.8)
    for _ in range(6):
        tracker.update(18.9)
    assert abs(tracker.fixed_height - 18.8) < 1e-9

    # Hovering around the new reference: no further events.
    assert tracker.update(18.8) is None
    assert tracker.update(19.0) is None
    assert tracker.fixed_height == 18.8

    # A new blockage (rise) is ignored by the tracker.
    assert tracker.update(20.0) is None
    assert tracker.fixed_height == 18.8

    # A new genuine decrease below the NEW reference re-triggers re-baselining.
    assert tracker.update(17.6) is None
    assert tracker.decrease_detected


def test_invalid_readings_are_ignored():
    """Zero/None heights are not valid readings and must not affect state."""
    tracker = ReferenceHeightTracker(initial_fixed_height_cm=20.0)
    tracker.update(20.0)
    assert tracker.update(0.0) is None
    assert tracker.update(None) is None
    assert tracker.fixed_height == 20.0