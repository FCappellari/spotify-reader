"""Script 2: Setlist Progression & Transition Evaluator.

Analyzes transitions in an enriched setlist, classifying harmonic
compatibility (Camelot Wheel) and BPM tempo progression, generating
counterproofs and track reordering suggestions, and outputting formatted
reports in terminal (Rich) and Markdown.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.camelot import classify_harmonic_transition
from src.config import (
    BPM_COMFORTABLE_PCT,
    BPM_MODERATE_PCT,
    HALF_DOUBLE_TIME_TOLERANCE,
    OUTPUT_DIR,
    ensure_dirs,
)
from src.models import (
    Setlist,
    Track,
    TransitionDetail,
    TransitionStatus,
)

# ---------------------------------------------------------------------------
# Status to score mapping for final verdict
# ---------------------------------------------------------------------------
_SCORE_MAP: dict[TransitionStatus, int] = {
    TransitionStatus.IDEAL: 10,
    TransitionStatus.GOOD_BOOST: 8,
    TransitionStatus.WARNING: 5,
    TransitionStatus.CRITICAL_ALERT: 0,
    TransitionStatus.MISSING_DATA: 3,
}

# ---------------------------------------------------------------------------
# Status to emoji mapping for reports
# ---------------------------------------------------------------------------
_EMOJI_MAP: dict[TransitionStatus, str] = {
    TransitionStatus.IDEAL: "✅",
    TransitionStatus.GOOD_BOOST: "🔵",
    TransitionStatus.WARNING: "⚠️",
    TransitionStatus.CRITICAL_ALERT: "🔴",
    TransitionStatus.MISSING_DATA: "❓",
}

# ---------------------------------------------------------------------------
# Status to friendly label mapping
# ---------------------------------------------------------------------------
_LABEL_MAP: dict[TransitionStatus, str] = {
    TransitionStatus.IDEAL: "Ideal",
    TransitionStatus.GOOD_BOOST: "Energy Boost",
    TransitionStatus.WARNING: "Warning",
    TransitionStatus.CRITICAL_ALERT: "Critical Alert",
    TransitionStatus.MISSING_DATA: "Missing Data",
}

# ---------------------------------------------------------------------------
# Status to Rich style (color) mapping
# ---------------------------------------------------------------------------
_STYLE_MAP: dict[TransitionStatus, str] = {
    TransitionStatus.IDEAL: "green",
    TransitionStatus.GOOD_BOOST: "cyan",
    TransitionStatus.WARNING: "yellow",
    TransitionStatus.CRITICAL_ALERT: "bold red",
    TransitionStatus.MISSING_DATA: "dim",
}


# ===================================================================
# 1. BPM Classification
# ===================================================================


def classify_bpm_transition(
    bpm_a: float | None,
    bpm_b: float | None,
) -> tuple[TransitionStatus, str, float | None, float | None]:
    """Classify tempo variation between two consecutive tracks.

    Calculates absolute and percentage delta, returning classification status,
    text description, absolute delta, and percentage delta.

    Args:
        bpm_a: BPM of source track (or ``None``).
        bpm_b: BPM of target track (or ``None``).

    Returns:
        Tuple ``(status, description, delta_abs, delta_pct)``.
    """
    if bpm_a is None or bpm_b is None:
        return (
            TransitionStatus.MISSING_DATA,
            "BPM not available for one of the tracks",
            None,
            None,
        )

    delta_abs: float = abs(bpm_b - bpm_a)
    delta_pct: float = delta_abs / bpm_a

    if delta_pct <= BPM_COMFORTABLE_PCT:
        return (
            TransitionStatus.IDEAL,
            f"Comfortable tempo shift ({delta_pct * 100:.1f}%)",
            delta_abs,
            delta_pct,
        )

    if delta_pct <= BPM_MODERATE_PCT:
        return (
            TransitionStatus.WARNING,
            f"Moderate tempo shift ({delta_pct * 100:.1f}%) — requires technical transition",
            delta_abs,
            delta_pct,
        )

    return (
        TransitionStatus.CRITICAL_ALERT,
        f"Sudden tempo jump ({delta_pct * 100:.1f}% / Δ{delta_abs:.0f} BPM) — rhythm break",
        delta_abs,
        delta_pct,
    )


# ===================================================================
# 2. Half / Double Time Verification
# ===================================================================


def check_half_double_time(bpm_a: float, bpm_b: float) -> bool:
    """Check whether two tracks have a half-time or double-time relationship.

    Returns ``True`` if any relative tempo ratio matches within
    the defined ``HALF_DOUBLE_TIME_TOLERANCE`` threshold (4%).

    Args:
        bpm_a: BPM of first track.
        bpm_b: BPM of second track.

    Returns:
        ``True`` if half/double time relationship is detected.
    """
    checks: list[float] = [
        abs((bpm_b * 2) - bpm_a) / bpm_a,
        abs((bpm_b / 2) - bpm_a) / bpm_a,
        abs((bpm_a * 2) - bpm_b) / bpm_b,
        abs((bpm_a / 2) - bpm_b) / bpm_b,
    ]
    return any(c <= HALF_DOUBLE_TIME_TOLERANCE for c in checks)


# ===================================================================
# 3. Better Candidate Cross-Check
# ===================================================================


def find_better_candidates(tracks: list[Track], current_idx: int) -> list[str]:
    """Search for other tracks in the setlist that would mix smoothly after current track.

    Scans tracks (excluding the current and immediate next track) and tests
    if transitioning would yield IDEAL or GOOD_BOOST harmonic compatibility
    and IDEAL BPM compatibility.

    Args:
        tracks: Full ordered list of tracks in the setlist.
        current_idx: 0-based index of current track.

    Returns:
        List of descriptive suggestion strings (up to 5 candidates).
    """
    current_track: Track = tracks[current_idx]
    suggestions: list[str] = []

    for k, candidate in enumerate(tracks):
        if k == current_idx or k == current_idx + 1:
            continue

        if not candidate.audio_features.found or not current_track.audio_features.found:
            continue

        harmonic_status, _ = classify_harmonic_transition(
            current_track.audio_features.camelot_code,
            candidate.audio_features.camelot_code,
        )

        bpm_status, _, _, _ = classify_bpm_transition(
            current_track.audio_features.bpm,
            candidate.audio_features.bpm,
        )

        if harmonic_status in (
            TransitionStatus.IDEAL,
            TransitionStatus.GOOD_BOOST,
        ) and bpm_status == TransitionStatus.IDEAL:
            suggestions.append(
                f"Track at position {candidate.position} "
                f"('{candidate.title}' - {candidate.audio_features.bpm} BPM / "
                f"{candidate.audio_features.camelot_code}) would fit "
                f"smoothly after track {current_track.position}."
            )

        if len(suggestions) >= 5:
            break

    return suggestions


# ===================================================================
# 4. Energy Curve Analysis
# ===================================================================


def analyze_energy_curve(tracks: list[Track]) -> str:
    """Analyze the overall energy curve of the set based on track BPMs.

    Divides the setlist into four quarters (Opening, Build-up, Peak, Closing)
    and checks if the tempo progression aligns with standard DJ arc patterns.

    Args:
        tracks: Ordered list of setlist tracks.

    Returns:
        Formatted descriptive string with energy curve insights.
    """
    bpm_tracks: list[tuple[int, float]] = [
        (i, t.audio_features.bpm)
        for i, t in enumerate(tracks)
        if t.audio_features.bpm is not None
    ]

    if len(bpm_tracks) < 4:
        return "Insufficient audio data for energy curve analysis."

    n: int = len(bpm_tracks)
    q1: int = n // 4
    q2: int = n // 2
    q3: int = (3 * n) // 4

    segments: dict[str, list[float]] = {
        "Opening": [bpm for _, bpm in bpm_tracks[:q1]],
        "Build-up": [bpm for _, bpm in bpm_tracks[q1:q2]],
        "Peak": [bpm for _, bpm in bpm_tracks[q2:q3]],
        "Closing": [bpm for _, bpm in bpm_tracks[q3:]],
    }

    averages: dict[str, float] = {}
    for name, bpms in segments.items():
        averages[name] = sum(bpms) / len(bpms) if bpms else 0.0

    lines: list[str] = ["📊 Average BPM per segment:"]
    for name, avg in averages.items():
        lines.append(f"  • {name}: {avg:.1f} BPM ({len(segments[name])} tracks)")

    lines.append("")

    opening = averages["Opening"]
    buildup = averages["Build-up"]
    peak = averages["Peak"]
    closing = averages["Closing"]

    observations: list[str] = []

    if opening < buildup <= peak and peak > closing:
        observations.append(
            "✅ The set follows the classic DJ arc: "
            "progressive build-up to a high-energy peak followed by a controlled wind-down."
        )
    else:
        if buildup < opening:
            observations.append(
                "⚠️ Energy dip detected between Opening and Build-up — "
                "consider moving lower-BPM tracks toward the beginning."
            )

        if peak < buildup:
            observations.append(
                "⚠️ Unexpected energy drop between Build-up and Peak — "
                "peak segment should feature higher intensity."
            )

        if closing > peak:
            observations.append(
                "⚠️ Closing segment energy exceeds the peak — "
                "set may lack a distinct climax point."
            )

    if opening <= buildup and buildup <= peak:
        observations.append(
            "📈 The set sustains a clean, upward energy progression up to the peak."
        )

    if peak > closing:
        observations.append(
            "📉 Smooth tempo deceleration during closing — good cooldown practice."
        )

    all_bpms: list[float] = [bpm for _, bpm in bpm_tracks]
    bpm_range: float = max(all_bpms) - min(all_bpms)
    lines.append(
        f"🎚️ Total BPM range: {min(all_bpms):.0f} – {max(all_bpms):.0f} "
        f"(Δ{bpm_range:.0f} BPM)"
    )
    lines.append("")

    for obs in observations:
        lines.append(obs)

    return "\n".join(lines)


# ===================================================================
# 5. Transition Evaluation
# ===================================================================


def evaluate_transitions(setlist: Setlist) -> list[TransitionDetail]:
    """Evaluate all consecutive transitions in the setlist.

    For each adjacent pair, classifies harmonic and BPM compatibility,
    applies counterproofs (half/double time, reordering suggestions),
    and returns a list of ``TransitionDetail`` records.

    Args:
        setlist: Setlist enriched with audio features.

    Returns:
        List of transition details for each consecutive track pair.
    """
    tracks: list[Track] = setlist.tracks
    transitions: list[TransitionDetail] = []

    for i in range(len(tracks) - 1):
        track_a: Track = tracks[i]
        track_b: Track = tracks[i + 1]

        harmonic_status, harmonic_detail = classify_harmonic_transition(
            track_a.audio_features.camelot_code,
            track_b.audio_features.camelot_code,
        )

        bpm_status, bpm_detail, bpm_delta_abs, bpm_delta_pct = classify_bpm_transition(
            track_a.audio_features.bpm,
            track_b.audio_features.bpm,
        )

        counterproofs: list[str] = []

        if not track_a.audio_features.found:
            counterproofs.append(
                f"Missing audio data for '{track_a.title}' — evaluation may be imprecise."
            )
        if not track_b.audio_features.found:
            counterproofs.append(
                f"Missing audio data for '{track_b.title}' — evaluation may be imprecise."
            )

        candidates_already_added: bool = False
        if (
            bpm_status == TransitionStatus.CRITICAL_ALERT
            and track_a.audio_features.bpm is not None
            and track_b.audio_features.bpm is not None
        ):
            if check_half_double_time(
                track_a.audio_features.bpm, track_b.audio_features.bpm
            ):
                bpm_status = TransitionStatus.WARNING
                bpm_detail += " (Half/Double Time compatible)"
                counterproofs.append(
                    "🔄 Half/Double Time relationship detected — "
                    "tempo difference can be smoothly blended with proper phrasing."
                )

            better: list[str] = find_better_candidates(tracks, i)
            if better:
                counterproofs.extend(better)
            candidates_already_added = True

        if (
            harmonic_status == TransitionStatus.CRITICAL_ALERT
            and not candidates_already_added
        ):
            better = find_better_candidates(tracks, i)
            if better:
                counterproofs.extend(better)

        transitions.append(
            TransitionDetail(
                from_position=track_a.position,
                to_position=track_b.position,
                from_track=f"{track_a.title} — {track_a.artist}",
                to_track=f"{track_b.title} — {track_b.artist}",
                harmonic_status=harmonic_status,
                harmonic_detail=harmonic_detail,
                bpm_status=bpm_status,
                bpm_detail=bpm_detail,
                bpm_delta_abs=bpm_delta_abs,
                bpm_delta_pct=bpm_delta_pct,
                counterproofs=counterproofs,
            )
        )

    return transitions


# ===================================================================
# Report Utilities
# ===================================================================


def _worst_status(a: TransitionStatus, b: TransitionStatus) -> TransitionStatus:
    """Return the more severe status between two, following severity hierarchy.

    Args:
        a: First status.
        b: Second status.

    Returns:
        The most severe status.
    """
    order: list[TransitionStatus] = [
        TransitionStatus.CRITICAL_ALERT,
        TransitionStatus.MISSING_DATA,
        TransitionStatus.WARNING,
        TransitionStatus.GOOD_BOOST,
        TransitionStatus.IDEAL,
    ]
    for status in order:
        if a == status or b == status:
            return status
    return a


def _count_by_status(
    transitions: list[TransitionDetail],
) -> dict[TransitionStatus, int]:
    """Count transitions grouped by worst status (Harmonic vs. BPM).

    Args:
        transitions: List of transition details.

    Returns:
        Dictionary mapping each ``TransitionStatus`` to its occurrence count.
    """
    counts: dict[TransitionStatus, int] = {s: 0 for s in TransitionStatus}
    for t in transitions:
        worst = _worst_status(t.harmonic_status, t.bpm_status)
        counts[worst] += 1
    return counts


def _compute_score(transitions: list[TransitionDetail]) -> float:
    """Calculate the average setlist rating (0.0 to 10.0).

    Args:
        transitions: List of transition details.

    Returns:
        Average setlist score.
    """
    if not transitions:
        return 0.0

    total: float = 0.0
    for t in transitions:
        worst = _worst_status(t.harmonic_status, t.bpm_status)
        total += _SCORE_MAP[worst]

    return total / len(transitions)


def _verdict_message(score: float) -> str:
    """Return a descriptive final assessment based on numerical score.

    Args:
        score: Average setlist score (0.0 - 10.0).

    Returns:
        Verdict message string.
    """
    if score >= 8:
        return "🏆 Excellent setlist! High-level harmonic and tempo progression."
    if score >= 6:
        return "👍 Good setlist, with a few attention points that can be refined."
    if score >= 4:
        return "⚠️ Setlist has significant rhythm or harmonic clashes. Reordering recommended."
    return "🔴 Multiple severe clashes detected. Full setlist review strongly recommended."


# ===================================================================
# 6. Terminal Report (Rich)
# ===================================================================


def generate_terminal_report(
    setlist: Setlist,
    transitions: list[TransitionDetail],
    energy_analysis: str,
) -> None:
    """Generate and display comprehensive visual terminal report using Rich.

    Includes header panel, summary table, detailed transition table,
    counterproofs and suggestions, energy curve analysis, and final verdict.

    Args:
        setlist: Analyzed setlist.
        transitions: Transition detail list.
        energy_analysis: Energy curve textual report.
    """
    console = Console()

    header_text = Text()
    header_text.append("🎧 DJ SETLIST ANALYZER", style="bold magenta")
    header_text.append("\n\n")
    header_text.append("📀 Playlist: ", style="bold white")
    header_text.append(setlist.playlist_name, style="bold cyan")
    header_text.append("\n")
    header_text.append("📅 Analysis Date: ", style="bold white")
    header_text.append(datetime.now().strftime("%Y-%m-%d %H:%M"), style="white")
    header_text.append("\n")
    header_text.append("🎵 Total Tracks: ", style="bold white")
    header_text.append(str(setlist.total_tracks), style="bold yellow")

    console.print()
    console.print(
        Panel(
            header_text,
            border_style="bright_magenta",
            title="[bold bright_white]PROGRESSION & HARMONIC EVALUATION[/]",
            subtitle="[dim]Script 2[/]",
            padding=(1, 3),
        )
    )
    console.print()

    counts = _count_by_status(transitions)
    summary_table = Table(
        title="📊 Transition Summary",
        title_style="bold white",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        padding=(0, 2),
    )
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Count", justify="center")

    for status in TransitionStatus:
        emoji = _EMOJI_MAP[status]
        label = _LABEL_MAP[status]
        style = _STYLE_MAP[status]
        summary_table.add_row(
            f"{emoji} {label}",
            str(counts[status]),
            style=style,
        )

    console.print(summary_table)
    console.print()

    detail_table = Table(
        title="🔀 Detailed Transitions",
        title_style="bold white",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        show_lines=True,
        padding=(0, 1),
    )
    detail_table.add_column("#", justify="center", width=4)
    detail_table.add_column("From → To", min_width=30)
    detail_table.add_column("BPM A → B (Δ%)", justify="center", min_width=18)
    detail_table.add_column("Camelot A → B", justify="center", min_width=14)
    detail_table.add_column("Harmonic", justify="center", min_width=14)
    detail_table.add_column("BPM", justify="center", min_width=14)

    for idx, t in enumerate(transitions, 1):
        worst = _worst_status(t.harmonic_status, t.bpm_status)
        style = _STYLE_MAP[worst]

        if t.bpm_delta_pct is not None:
            bpm_cell = (
                f"{t.bpm_delta_abs:.0f} BPM / {t.bpm_delta_pct * 100:.1f}%"
            )
        else:
            bpm_cell = "—"

        track_a = setlist.tracks[idx - 1]
        track_b = setlist.tracks[idx] if idx < len(setlist.tracks) else None
        camelot_a = track_a.audio_features.camelot_code or "?"
        camelot_b = (track_b.audio_features.camelot_code or "?") if track_b else "?"

        h_emoji = _EMOJI_MAP[t.harmonic_status]
        b_emoji = _EMOJI_MAP[t.bpm_status]

        detail_table.add_row(
            str(idx),
            f"{t.from_track}\n→ {t.to_track}",
            bpm_cell,
            f"{camelot_a} → {camelot_b}",
            f"{h_emoji} {t.harmonic_status.value}",
            f"{b_emoji} {t.bpm_status.value}",
            style=style,
        )

    console.print(detail_table)
    console.print()

    has_counterproofs: bool = any(t.counterproofs for t in transitions)
    if has_counterproofs:
        console.print(
            Panel(
                "[bold bright_yellow]🔍 COUNTERPROOFS & REORDERING SUGGESTIONS[/]",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        for idx, t in enumerate(transitions, 1):
            if t.counterproofs:
                cp_text = Text()
                cp_text.append(
                    f"Transition {t.from_position} → {t.to_position}: ",
                    style="bold yellow",
                )
                cp_text.append(
                    f"{t.from_track} → {t.to_track}\n",
                    style="white",
                )
                for cp in t.counterproofs:
                    cp_text.append(f"  • {cp}\n", style="bright_yellow")

                console.print(
                    Panel(
                        cp_text,
                        border_style="yellow",
                        padding=(0, 2),
                    )
                )
        console.print()

    console.print(
        Panel(
            energy_analysis,
            title="[bold bright_white]📈 Energy Curve Analysis[/]",
            border_style="bright_green",
            padding=(1, 3),
        )
    )
    console.print()

    score: float = _compute_score(transitions)
    verdict: str = _verdict_message(score)

    verdict_text = Text()
    verdict_text.append("🎯 OVERALL SCORE: ", style="bold white")
    score_style = (
        "bold green" if score >= 8
        else "bold cyan" if score >= 6
        else "bold yellow" if score >= 4
        else "bold red"
    )
    verdict_text.append(f"{score:.1f}/10", style=score_style)
    verdict_text.append("\n\n")
    verdict_text.append(verdict, style="bold white")

    console.print(
        Panel(
            verdict_text,
            title="[bold bright_white]🏆 FINAL VERDICT[/]",
            border_style="bright_magenta",
            padding=(1, 3),
        )
    )
    console.print()


# ===================================================================
# 7. Markdown Report
# ===================================================================


def generate_markdown_report(
    setlist: Setlist,
    transitions: list[TransitionDetail],
    energy_analysis: str,
) -> str:
    """Generate complete setlist evaluation in Markdown format.

    Args:
        setlist: Analyzed setlist.
        transitions: List of transition details.
        energy_analysis: Energy curve textual summary.

    Returns:
        Formatted Markdown report string.
    """
    lines: list[str] = []

    lines.append("# 🎧 DJ Setlist Evaluation Report")
    lines.append("")
    lines.append(f"**Playlist:** {setlist.playlist_name}  ")
    lines.append(
        f"**Analysis Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  "
    )
    lines.append(f"**Total Tracks:** {setlist.total_tracks}")
    lines.append("")
    lines.append("---")

    lines.append("")
    lines.append("## 📊 Transition Summary")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")

    counts = _count_by_status(transitions)
    for status in TransitionStatus:
        emoji = _EMOJI_MAP[status]
        label = _LABEL_MAP[status]
        lines.append(f"| {emoji} {label} | {counts[status]} |")

    lines.append("")
    lines.append("---")

    lines.append("")
    lines.append("## 🔀 Detailed Transitions")
    lines.append("")
    lines.append("| # | From | To | BPM (Δ%) | Camelot | Harmonic | BPM |")
    lines.append("|---|------|----|----------|---------|----------|-----|")

    for idx, t in enumerate(transitions, 1):
        if t.bpm_delta_pct is not None:
            bpm_cell = f"Δ{t.bpm_delta_abs:.0f} / {t.bpm_delta_pct * 100:.1f}%"
        else:
            bpm_cell = "—"

        track_a = setlist.tracks[idx - 1]
        track_b = setlist.tracks[idx] if idx < len(setlist.tracks) else None
        camelot_a = track_a.audio_features.camelot_code or "?"
        camelot_b = (track_b.audio_features.camelot_code or "?") if track_b else "?"

        h_emoji = _EMOJI_MAP[t.harmonic_status]
        b_emoji = _EMOJI_MAP[t.bpm_status]

        lines.append(
            f"| {idx} "
            f"| {t.from_track} "
            f"| {t.to_track} "
            f"| {bpm_cell} "
            f"| {camelot_a} → {camelot_b} "
            f"| {h_emoji} {t.harmonic_status.value} "
            f"| {b_emoji} {t.bpm_status.value} |"
        )

    lines.append("")
    lines.append("---")

    lines.append("")
    lines.append("## 🔍 Counterproofs & Suggestions")
    lines.append("")

    has_counterproofs = any(t.counterproofs for t in transitions)
    if has_counterproofs:
        for idx, t in enumerate(transitions, 1):
            if t.counterproofs:
                lines.append(
                    f"### Transition {t.from_position} → {t.to_position}"
                )
                lines.append(
                    f"**{t.from_track}** → **{t.to_track}**"
                )
                lines.append("")
                for cp in t.counterproofs:
                    lines.append(f"- {cp}")
                lines.append("")
    else:
        lines.append("No counterproofs required — all transitions are within optimal ranges. 🎉")
        lines.append("")

    lines.append("---")

    lines.append("")
    lines.append("## 📈 Energy Curve Analysis")
    lines.append("")
    lines.append(energy_analysis)
    lines.append("")
    lines.append("---")

    score: float = _compute_score(transitions)
    verdict: str = _verdict_message(score)

    lines.append("")
    lines.append("## 🏆 Final Verdict")
    lines.append("")
    lines.append(f"**Score:** {score:.1f}/10")
    lines.append("")
    lines.append(verdict)
    lines.append("")

    return "\n".join(lines)


# ===================================================================
# 8. Main Entry Point
# ===================================================================


def main() -> None:
    """Main CLI entry point for setlist evaluation.

    Loads the enriched setlist JSON, evaluates transitions, prints rich
    terminal output, and persists the Markdown report.
    """
    ensure_dirs()
    console = Console()

    input_path: Path = OUTPUT_DIR / "setlist_enriched.json"
    output_path: Path = OUTPUT_DIR / "evaluation_report.md"

    try:
        raw_data: str = input_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        console.print(
            Panel(
                "[bold red]❌ 'setlist_enriched.json' not found![/]\n\n"
                "Please run the extraction script first:\n"
                "  [bold cyan]python -m src.extract_setlist[/]",
                border_style="red",
                title="[bold red]ERROR[/]",
                padding=(1, 3),
            )
        )
        return

    setlist: Setlist = Setlist.model_validate(json.loads(raw_data))

    console.print()
    console.print(
        "[bold bright_magenta]⏳ Evaluating setlist transitions...[/]"
    )
    console.print()

    transitions: list[TransitionDetail] = evaluate_transitions(setlist)
    energy_analysis: str = analyze_energy_curve(setlist.tracks)

    generate_terminal_report(setlist, transitions, energy_analysis)

    md_report: str = generate_markdown_report(setlist, transitions, energy_analysis)
    output_path.write_text(md_report, encoding="utf-8")

    console.print(
        Panel(
            f"[bold green]✅ Report successfully saved![/]\n\n"
            f"📄 Path: [bold cyan]{output_path.resolve()}[/]",
            border_style="green",
            title="[bold green]COMPLETED[/]",
            padding=(1, 3),
        )
    )
    console.print()


if __name__ == "__main__":
    main()
