"""Camelot Wheel logic module for harmonic mixing analysis."""

from __future__ import annotations

import re

from src.models import TransitionStatus

# ---------------------------------------------------------------------------
# Open Key (Traktor) → Camelot mapping
# ---------------------------------------------------------------------------
OPEN_KEY_TO_CAMELOT: dict[str, str] = {
    "1m": "8A",  "1d": "8B",
    "2m": "9A",  "2d": "9B",
    "3m": "10A", "3d": "10B",
    "4m": "11A", "4d": "11B",
    "5m": "12A", "5d": "12B",
    "6m": "1A",  "6d": "1B",
    "7m": "2A",  "7d": "2B",
    "8m": "3A",  "8d": "3B",
    "9m": "4A",  "9d": "4B",
    "10m": "5A", "10d": "5B",
    "11m": "6A", "11d": "6B",
    "12m": "7A", "12d": "7B",
}

# ---------------------------------------------------------------------------
# Musical key name → Camelot mapping
# ---------------------------------------------------------------------------
KEY_OF_TO_CAMELOT: dict[str, str] = {
    # 1A / 1B
    "Ab minor": "1A", "Abm": "1A", "G#m": "1A", "G# minor": "1A",
    "B major": "1B", "B": "1B",
    # 2A / 2B
    "Eb minor": "2A", "Ebm": "2A", "D#m": "2A", "D# minor": "2A",
    "F# major": "2B", "Gb major": "2B", "F#": "2B", "Gb": "2B",
    # 3A / 3B
    "Bb minor": "3A", "Bbm": "3A", "A#m": "3A", "A# minor": "3A",
    "Db major": "3B", "C# major": "3B", "Db": "3B", "C#": "3B",
    # 4A / 4B
    "F minor": "4A", "Fm": "4A",
    "Ab major": "4B", "G# major": "4B", "Ab": "4B",
    # 5A / 5B
    "C minor": "5A", "Cm": "5A",
    "Eb major": "5B", "D# major": "5B", "Eb": "5B",
    # 6A / 6B
    "G minor": "6A", "Gm": "6A",
    "Bb major": "6B", "A# major": "6B", "Bb": "6B",
    # 7A / 7B
    "D minor": "7A", "Dm": "7A",
    "F major": "7B", "F": "7B",
    # 8A / 8B
    "A minor": "8A", "Am": "8A",
    "C major": "8B", "C": "8B",
    # 9A / 9B
    "E minor": "9A", "Em": "9A",
    "G major": "9B", "G": "9B",
    # 10A / 10B
    "B minor": "10A", "Bm": "10A",
    "D major": "10B", "D": "10B",
    # 11A / 11B
    "F# minor": "11A", "F#m": "11A", "Gb minor": "11A", "Gbm": "11A",
    "A major": "11B", "A": "11B",
    # 12A / 12B
    "C# minor": "12A", "C#m": "12A", "Db minor": "12A", "Dbm": "12A",
    "E major": "12B", "E": "12B",
}


def convert_to_camelot(open_key: str | None, key_of: str | None) -> str | None:
    """Convert an Open Key code or musical key name into standard Camelot notation.

    Tries ``open_key`` (Traktor format) first. If not found, falls back
    to ``key_of`` (standard musical notation).

    Args:
        open_key: Open Key value (e.g., ``"1m"``, ``"5d"``).
        key_of: Musical key name (e.g., ``"A minor"``, ``"Cm"``).

    Returns:
        Camelot code (e.g., ``"8A"``) or ``None`` if conversion is not possible.
    """
    if open_key is not None:
        normalized = open_key.strip().lower()
        result = OPEN_KEY_TO_CAMELOT.get(normalized)
        if result is not None:
            return result

    if key_of is not None:
        normalized = key_of.strip()
        result = KEY_OF_TO_CAMELOT.get(normalized)
        if result is not None:
            return result

    return None


def parse_camelot(code: str) -> tuple[int, str]:
    """Decompose a Camelot code into number and letter.

    Args:
        code: Camelot code (e.g., ``"8A"``, ``"12B"``).

    Returns:
        Tuple ``(number, letter)`` — for example ``(8, "A")`` or ``(12, "B")``.

    Raises:
        ValueError: If the code does not match expected Camelot pattern.
    """
    match = re.match(r"^(\d{1,2})([AB])$", code)
    if not match:
        raise ValueError(f"Invalid Camelot code: '{code}'")
    return int(match.group(1)), match.group(2)


def camelot_distance(code_a: str, code_b: str) -> tuple[int, bool]:
    """Calculate circular distance between two Camelot codes on the wheel.

    Args:
        code_a: First Camelot code.
        code_b: Second Camelot code.

    Returns:
        Tuple ``(distance, same_letter)`` where distance is shortest circular
        distance (0-6) when letters match, and same_letter indicates if both
        share the same mode (A = minor, B = major).
    """
    num_a, letter_a = parse_camelot(code_a)
    num_b, letter_b = parse_camelot(code_b)
    same_letter: bool = letter_a == letter_b

    if same_letter:
        diff = abs(num_a - num_b)
        distance = min(diff, 12 - diff)
    else:
        distance = abs(num_a - num_b)

    return distance, same_letter


def classify_harmonic_transition(
    camelot_a: str | None,
    camelot_b: str | None,
) -> tuple[TransitionStatus, str]:
    """Classify the harmonic transition between two tracks based on Camelot codes.

    Classification rules (in priority order):
    - Same key -> ``IDEAL``
    - Relative Major/Minor (same number, different letter) -> ``IDEAL``
    - Adjacent on wheel (+-1, same letter) -> ``IDEAL``
    - Energy Boost (+2 or +7, same letter) -> ``GOOD_BOOST``
    - Any other combination -> ``CRITICAL_ALERT``
    - Missing data -> ``MISSING_DATA``

    Args:
        camelot_a: Camelot code of first track (or ``None``).
        camelot_b: Camelot code of second track (or ``None``).

    Returns:
        Tuple ``(status, description)`` with classification result.
    """
    if camelot_a is None or camelot_b is None:
        return (
            TransitionStatus.MISSING_DATA,
            "Key not available for one of the tracks",
        )

    num_a, letter_a = parse_camelot(camelot_a)
    num_b, letter_b = parse_camelot(camelot_b)

    same_number: bool = num_a == num_b
    same_letter: bool = letter_a == letter_b

    # Same key
    if same_number and same_letter:
        return (
            TransitionStatus.IDEAL,
            f"Same key ({camelot_a})",
        )

    # Relative Major / Minor
    if same_number and not same_letter:
        return (
            TransitionStatus.IDEAL,
            f"Relative Major/Minor ({camelot_a} → {camelot_b})",
        )

    # Circular distance (same mode / letter)
    if same_letter:
        diff = abs(num_a - num_b)
        distance: int = min(diff, 12 - diff)

        if distance == 1:
            return (
                TransitionStatus.IDEAL,
                "Adjacent on Camelot Wheel (±1)",
            )

        if distance == 2:
            return (
                TransitionStatus.GOOD_BOOST,
                "Energy Boost (+2)",
            )

        if distance == 7:
            return (
                TransitionStatus.GOOD_BOOST,
                "Energy Boost (+7)",
            )

        return (
            TransitionStatus.CRITICAL_ALERT,
            f"Harmonic Clash (distance {distance} on Camelot Wheel)",
        )

    # Different letters and different numbers -> clash
    diff = abs(num_a - num_b)
    distance = min(diff, 12 - diff)
    return (
        TransitionStatus.CRITICAL_ALERT,
        f"Harmonic Clash (distance {distance} on Camelot Wheel)",
    )
