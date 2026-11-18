"""Script 1: Setlist Extractor & Enricher.

Extracts tracks from a Spotify playlist, enriches each track with BPM and key data
via the GetSongBPM API, and saves the complete setlist to a structured JSON file.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import spotipy
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.status import Status

from src.camelot import convert_to_camelot
from src.config import (
    CACHE_DIR,
    GETSONGBPM_API_KEY,
    GETSONGBPM_BASE_URL,
    GETSONGBPM_RATE_LIMIT_SLEEP,
    OUTPUT_DIR,
    SPOTIPY_CLIENT_ID,
    SPOTIPY_REDIRECT_URI,
    ensure_dirs,
)
from src.models import AudioFeatures, Setlist, Track


def parse_playlist_id(url_or_id: str) -> str:
    """Extract the playlist ID from a Spotify URL or raw ID.

    Args:
        url_or_id: Full Spotify URL or raw playlist ID.

    Returns:
        Extracted playlist ID string.
    """
    match = re.search(r"playlist[/:]([a-zA-Z0-9]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()


def clean_track_title(title: str) -> str:
    """Clean common Spotify suffixes that hinder GetSongBPM matching.

    Args:
        title: Original track title.

    Returns:
        Cleaned track title without unnecessary suffixes.
    """
    patterns: list[str] = [
        r"\s*-\s*Radio Edit$",
        r"\s*-\s*Original Mix$",
        r"\s*-\s*Remastered\s+\d{4}$",
        r"\s*-\s*Remastered$",
        r"\s*-\s*Extended Mix$",
        r"\s*-\s*Club Mix$",
        r"\s*-\s*Deluxe Edition$",
        r"\s*-\s*Bonus Track$",
        r"\s*\(feat\.[^)]*\)$",
        r"\s*\(with\s[^)]*\)$",
        r"\s*\(Remix\)$",
        r"\s*\[Remastered\]$",
    ]

    cleaned: str = title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


def load_cache() -> dict:
    """Load GetSongBPM cache from the local JSON file.

    Returns:
        Cached data dictionary, or an empty dictionary if not present.
    """
    cache_file: Path = CACHE_DIR / "getsongbpm_cache.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict) -> None:
    """Save GetSongBPM cache to the local JSON file.

    Args:
        cache: Dictionary containing data to persist.
    """
    cache_file: Path = CACHE_DIR / "getsongbpm_cache.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def fetch_getsongbpm(
    title: str,
    artist: str,
    api_key: str,
    cache: dict,
    spotify_id: str,
) -> AudioFeatures:
    """Query BPM and key data from the GetSongBPM API, using local cache.

    Args:
        title: Cleaned track title.
        artist: Primary artist name.
        api_key: GetSongBPM API key.
        cache: Cache dictionary.
        spotify_id: Spotify track ID (used as cache key).

    Returns:
        AudioFeatures object with retrieved data or found=False.
    """
    if spotify_id in cache:
        cached_data: dict = cache[spotify_id]
        return AudioFeatures(**cached_data)

    try:
        with httpx.Client(timeout=15) as client:
            params: dict = {
                "type": "both",
                "lookup": f"song:{title} artist:{artist}",
                "limit": 3,
                "api_key": api_key,
            }
            response = client.get(f"{GETSONGBPM_BASE_URL}/search/", params=params)
            response.raise_for_status()
            data: dict = response.json()

        results: list = data.get("search", data if isinstance(data, list) else [])

        if not results:
            return AudioFeatures(found=False)

        first_result: dict = results[0]
        tempo: float = float(first_result["tempo"])
        key_of: str = first_result["key_of"]
        open_key: str = first_result["open_key"]

        camelot_code: str | None = convert_to_camelot(open_key, key_of)

        audio_features = AudioFeatures(
            found=True,
            bpm=tempo,
            key_of=key_of,
            open_key=open_key,
            camelot_code=camelot_code,
        )

        cache[spotify_id] = audio_features.model_dump()
        save_cache(cache)

        return audio_features

    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return AudioFeatures(found=False)

    finally:
        time.sleep(GETSONGBPM_RATE_LIMIT_SLEEP)


def extract_playlist_tracks(
    sp: spotipy.Spotify,
    playlist_id: str,
) -> tuple[str, list[dict]]:
    """Extract all tracks from a Spotify playlist with full pagination.

    Args:
        sp: Authenticated Spotipy client.
        playlist_id: Spotify playlist ID.

    Returns:
        Tuple of playlist title and list of raw track items.
    """
    playlist_info: dict = sp.playlist(playlist_id, fields="name")
    playlist_name: str = playlist_info["name"]

    all_tracks: list[dict] = []
    offset: int = 0
    fields: str = "items(track(id,name,artists,duration_ms,external_ids)),next,total"

    while True:
        results: dict = sp.playlist_items(
            playlist_id,
            fields=fields,
            limit=50,
            offset=offset,
        )

        items: list[dict] = results.get("items", [])
        for item in items:
            track: dict | None = item.get("track")
            if track is not None:
                all_tracks.append(track)

        if results.get("next") is None:
            break

        offset += 50

    return playlist_name, all_tracks


def main() -> None:
    """Main CLI entry point for the setlist extractor.

    Orchestrates track extraction from Spotify, GetSongBPM data enrichment,
    and JSON setlist export.
    """
    ensure_dirs()
    console = Console()

    try:
        if len(sys.argv) > 1:
            playlist_input: str = sys.argv[1]
        else:
            playlist_input = console.input(
                "🎵 Enter Spotify playlist link or ID: "
            )

        playlist_id: str = parse_playlist_id(playlist_input)

        sp = spotipy.SpotifyPKCE(
            client_id=SPOTIPY_CLIENT_ID,
            redirect_uri=SPOTIPY_REDIRECT_URI,
            scope="playlist-read-private playlist-read-collaborative",
        )

        console.print(
            Panel(
                "[bold magenta]🎧 Setlist Extractor & Enricher[/bold magenta]\n"
                f"[dim]Playlist ID: {playlist_id}[/dim]",
                border_style="bright_magenta",
                expand=False,
            )
        )

        with Status(
            "[bold cyan]Fetching playlist tracks...[/bold cyan]",
            console=console,
            spinner="dots",
        ):
            playlist_name, raw_tracks = extract_playlist_tracks(sp, playlist_id)

        console.print(
            f"\n[bold green]✅ Playlist:[/bold green] [italic]{playlist_name}[/italic]"
            f" — [bold]{len(raw_tracks)}[/bold] tracks found\n"
        )

        cache: dict = load_cache()
        tracks: list[Track] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(
                "[cyan]Enriching tracks...",
                total=len(raw_tracks),
            )

            for idx, raw_track in enumerate(raw_tracks, start=1):
                track_name: str = raw_track.get("name", "Unknown")
                artists: list[dict] = raw_track.get("artists", [])
                artist_name: str = artists[0]["name"] if artists else "Unknown"
                duration_ms: int = raw_track.get("duration_ms", 0)
                spotify_id: str = raw_track.get("id", "")

                external_ids: dict = raw_track.get("external_ids", {})
                isrc: str | None = external_ids.get("isrc") if external_ids else None

                cleaned_title: str = clean_track_title(track_name)

                audio_features: AudioFeatures = fetch_getsongbpm(
                    title=cleaned_title,
                    artist=artist_name,
                    api_key=GETSONGBPM_API_KEY,
                    cache=cache,
                    spotify_id=spotify_id,
                )

                track = Track(
                    position=idx,
                    title=track_name,
                    clean_title=cleaned_title,
                    artist=artist_name,
                    duration_ms=duration_ms,
                    spotify_id=spotify_id,
                    isrc=isrc,
                    audio_features=audio_features,
                )
                tracks.append(track)

                progress.update(task_id, advance=1)

        setlist = Setlist(
            playlist_id=playlist_id,
            playlist_name=playlist_name,
            extracted_at=datetime.utcnow().isoformat() + "Z",
            total_tracks=len(tracks),
            tracks=tracks,
        )

        output_path: Path = OUTPUT_DIR / "setlist_enriched.json"
        output_path.write_text(setlist.model_dump_json(indent=2), encoding="utf-8")

        found_count: int = sum(1 for t in tracks if t.audio_features.found)
        missing_count: int = len(tracks) - found_count

        console.print(
            Panel(
                f"[bold green]📊 Extraction Summary[/bold green]\n\n"
                f"  🎵 Total tracks extracted:         [bold]{len(tracks)}[/bold]\n"
                f"  ✅ With audio data (BPM / Key):     [bold green]{found_count}[/bold green]\n"
                f"  ❌ Missing audio data:              [bold red]{missing_count}[/bold red]\n\n"
                f"  💾 Output saved to: [underline]{output_path}[/underline]",
                border_style="bright_green",
                expand=False,
            )
        )

    except spotipy.SpotifyException as e:
        console.print(f"\n[bold red]❌ Spotify Error:[/bold red] {e}")
        sys.exit(1)

    except httpx.HTTPError as e:
        console.print(f"\n[bold red]❌ Network (HTTP) Error:[/bold red] {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]⚠️  Execution interrupted by user.[/bold yellow]")
        sys.exit(0)

    except Exception:
        console.print("\n[bold red]❌ Unexpected Error:[/bold red]")
        console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    main()
