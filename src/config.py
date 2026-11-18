"""Configuration module for DJ Setlist Analyzer.

Loads environment variables from .env and exposes threshold constants
used in transition analysis between tracks.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def from_dotenv() -> None:
    """Load environment variables defined in the .env file."""
    load_dotenv()


# ---------------------------------------------------------------------------
# Load .env automatically upon importing the module
# ---------------------------------------------------------------------------
from_dotenv()

# ---------------------------------------------------------------------------
# Credentials read from the environment
# ---------------------------------------------------------------------------
SPOTIPY_CLIENT_ID: str = os.environ.get("SPOTIPY_CLIENT_ID", "")
SPOTIPY_REDIRECT_URI: str = os.environ.get("SPOTIPY_REDIRECT_URI", "")
GETSONGBPM_API_KEY: str = os.environ.get("GETSONGBPM_API_KEY", "")

# ---------------------------------------------------------------------------
# BPM analysis threshold constants
# ---------------------------------------------------------------------------
BPM_COMFORTABLE_PCT: float = 0.035
"""Percentage BPM variation considered comfortable (<= 3.5%)."""

BPM_MODERATE_PCT: float = 0.06
"""Percentage BPM variation considered moderate (<= 6.0%)."""

HALF_DOUBLE_TIME_TOLERANCE: float = 0.04
"""Tolerance for half-time / double-time detection (4%)."""

# ---------------------------------------------------------------------------
# GetSongBPM API settings
# ---------------------------------------------------------------------------
GETSONGBPM_BASE_URL: str = "https://api.getsong.co"
"""Base URL for the GetSongBPM API."""

GETSONGBPM_RATE_LIMIT_SLEEP: float = 0.2
"""Wait time in seconds between requests to respect rate limits."""

# ---------------------------------------------------------------------------
# Cache and output directories
# ---------------------------------------------------------------------------
CACHE_DIR: Path = Path("cache")
"""Directory for local cache storage."""

OUTPUT_DIR: Path = Path("output")
"""Directory for output files generated during analysis."""


def ensure_dirs() -> None:
    """Create cache and output directories if they do not exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
