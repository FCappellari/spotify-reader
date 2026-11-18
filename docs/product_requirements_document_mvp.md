# PRD — DJ Setlist Harmonic & Tempo Analyzer (MVP)

## 1. Overview and Objective
The goal of this MVP is to validate the feasibility of analyzing the technical fluidity of a DJ setlist arranged within a Spotify playlist, without requiring a complex database setup. The system extracts the exact sequence of tracks from a specified playlist, enriches each track with musical metadata (BPM and Key) via an external API, and executes an evaluation engine to identify tempo clashes, harmonic dissonance, and suggest attention points or track reordering.

---

## 2. MVP Scope
The project is split into **two independent scripts** connected by a structured intermediate artifact (`output/setlist_enriched.json`), allowing multiple re-evaluations without redundant API calls.

### Script 1: Extractor & Enricher (`src/extract_setlist.py`)
* **Authentication:** Connects to the user's Spotify account via OAuth 2.0 (Authorization Code with PKCE) and automatic token refresh handling.
* **Playlist Selection:** Accepts a Spotify playlist URL or ID.
* **Sequential Extraction:** Reads all tracks strictly preserving playlist order (`position: 1..N`), extracting title, primary artist, duration, and ISRC.
* **External Enrichment (GetSongBPM API):** Queries musical metadata per track and appends `bpm`, `key_of`, `open_key`, and normalized `camelot_code`.
* **Output:** Saves a consolidated JSON file (`output/setlist_enriched.json`) containing complete metadata for the playlist and all tracks in sequence.

### Script 2: Progression & Transition Evaluator (`src/evaluate_setlist.py`)
* **Input:** Consumes `output/setlist_enriched.json`.
* **Pairwise Transition Analysis:** Evaluates each consecutive transition (`Track N -> Track N+1`) across three core pillars:
  1. **Harmonic Compatibility (Camelot Wheel):** Classifies transition (Same Key, Adjacent ±1, Relative Major/Minor, Energy Boost +2/+7, or Harmonic Clash).
  2. **Tempo Progression (BPM / Pitch):** Calculates percentage (`Δ%`) and absolute (`Δ BPM`) variations, detecting abrupt shifts (> ±3.5% or > ±6.0%) and identifying half-time/double-time relationships.
  3. **Energy Arc / Global Progression:** Analyzes the set arc (Opening, Build-up, Peak, and Closing) and handles missing metadata gracefully.
* **Counterproof Logic:** For each detected critical issue in transition `N -> N+1`:
  * Verifies whether another track in the playlist would resolve the transition smoothly in both key and tempo (reordering suggestion).
  * Validates whether tempo differences are merely half-time/double-time readings (e.g., `70 BPM` vs `140 BPM`), preventing false positives.
* **Output:** Generates a visual terminal report (via Rich) and a Markdown report (`output/evaluation_report.md`).

---

## 3. Definition of Done (Acceptance Criteria)
1. The user can run Script 1 with only a playlist link/ID and receive the enriched JSON without pagination or authentication errors.
2. At least 80% of commercial tracks return valid BPM and Key from GetSongBPM (with graceful fallbacks for unreleased tracks or edits).
3. Script 2 clearly identifies harmonic clashes and abrupt BPM jumps, presenting counterproofs (internal reordering suggestions or half/double-time recognition).

---

## 4. Out of Scope (Post-MVP)
* Relational database persistence (PostgreSQL / SQLite).
* Web frontend UI or graphic visualizer.
* Querying tracks outside the current playlist to fill gaps.
* Local audio file analysis (`.mp3` / `.wav`) via Essentia / Librosa.
