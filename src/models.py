"""Pydantic v2 models for the DJ Setlist Analyzer.

Defines data structures representing tracks, audio features,
setlists, and transition details between tracks.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AudioFeatures(BaseModel):
    """Audio features of a track retrieved from an external API."""

    found: bool
    """Indicates whether audio information was found."""

    source: str = "getsongbpm"
    """Data source for audio features (e.g., 'getsongbpm')."""

    bpm: Optional[float] = None
    """Beats per minute of the track."""

    key_of: Optional[str] = None
    """Musical key of the track (e.g., 'Am', 'C')."""

    open_key: Optional[str] = None
    """Open Key notation of the musical key."""

    camelot_code: Optional[str] = None
    """Camelot code of the musical key (e.g., '8A', '5B')."""

    danceability: Optional[int] = None
    """Danceability index (0-100)."""


class Track(BaseModel):
    """Representation of a track within a setlist."""

    position: int
    """Track position in the playlist (1-based index)."""

    spotify_id: str
    """Spotify unique track identifier."""

    isrc: Optional[str] = None
    """International Standard Recording Code (ISRC)."""

    title: str
    """Original track title as displayed on Spotify."""

    clean_title: str
    """Cleaned track title without extra metadata (remix, feat., etc.)."""

    artist: str
    """Primary artist name."""

    duration_ms: int
    """Track duration in milliseconds."""

    audio_features: AudioFeatures
    """Audio features associated with the track."""


class Setlist(BaseModel):
    """Full representation of a setlist extracted from a Spotify playlist."""

    playlist_id: str
    """Spotify playlist identifier."""

    playlist_name: str
    """Spotify playlist title."""

    extracted_at: str
    """Extraction timestamp in ISO 8601 format."""

    total_tracks: int
    """Total number of tracks in the setlist."""

    tracks: list[Track]
    """Ordered list of tracks in the setlist."""


class TransitionStatus(str, Enum):
    """Possible statuses for a transition between two consecutive tracks."""

    IDEAL = "IDEAL"
    """Ideal transition - perfect harmonic and BPM compatibility."""

    GOOD_BOOST = "GOOD (BOOST)"
    """Good transition with energy boost potential."""

    WARNING = "WARNING"
    """Transition requiring DJ attention / technical transition."""

    CRITICAL_ALERT = "CRITICAL ALERT"
    """Critical transition - significant harmonic clash or tempo jump."""

    MISSING_DATA = "MISSING DATA"
    """Insufficient audio data to evaluate transition."""


class TransitionDetail(BaseModel):
    """Detailed evaluation of a transition between two consecutive tracks."""

    from_position: int
    """Position of the source track in the setlist."""

    to_position: int
    """Position of the target track in the setlist."""

    from_track: str
    """Source track identification (Title - Artist)."""

    to_track: str
    """Target track identification (Title - Artist)."""

    harmonic_status: TransitionStatus
    """Harmonic compatibility status of the transition."""

    harmonic_detail: str
    """Detailed description of harmonic analysis."""

    bpm_status: TransitionStatus
    """BPM compatibility status of the transition."""

    bpm_detail: str
    """Detailed description of BPM analysis."""

    bpm_delta_abs: Optional[float] = None
    """Absolute difference in BPM between the tracks."""

    bpm_delta_pct: Optional[float] = None
    """Percentage difference in BPM between the tracks."""

    counterproofs: list[str] = Field(default_factory=list)
    """List of counterproofs, cross-checks, or reordering suggestions."""
