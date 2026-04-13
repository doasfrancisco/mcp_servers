"""Spotify MCP Server — search, playlists, playback control."""

import json
import logging
import random as _random
from logging.handlers import RotatingFileHandler
from pathlib import Path

_log_dir = Path(__file__).parent / "logs"
_log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[RotatingFileHandler(_log_dir / "spotify.log", maxBytes=5_000_000, backupCount=1)],
)

from fastmcp import FastMCP

from spotify_client import build_client

mcp = FastMCP(
    "Spotify",
    instructions="""IMPORTANT: Always discover a tool's schema with ToolSearch BEFORE calling it for the first time.

When the user asks to play music — whether "play a song", "play something", "play a calming song", "play something upbeat", etc. — ALWAYS use the user's Liked Songs as the source. Never search Spotify. The flow is:
1. Call spotify_list_tracks("liked") to get their Liked Songs
2. Pick a song that matches what they asked for (e.g. calming, energetic, etc.)
3. Play it with spotify_play

If they say "play something" with no preference, use spotify_play with random=true for a random pick.

Do NOT ask for confirmation before playing. Just play the song immediately and tell the user what's playing.

When presenting track results, format as:
  1. **Track Name** — Artist(s) · Album
     URI: spotify:track:xxx

When presenting playlists, format as:
  1. **Playlist Name** — N tracks · owner
""",
)

_sp = None


def _get_sp():
    global _sp
    if _sp is None:
        _sp = build_client()
    return _sp


def _json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _format_track(track: dict) -> dict:
    """Extract the useful fields from a track object."""
    album = track.get("album") or {}
    return {
        "name": track.get("name", "Unknown"),
        "artists": [a["name"] for a in track.get("artists", [])],
        "album": album.get("name", "Unknown"),
        "uri": track.get("uri", ""),
        "duration_ms": track.get("duration_ms", 0),
    }


# ── Search ────────────────────────────────────────────────────────────


@mcp.tool()
def spotify_search(
    query: str,
    type: str = "track",
) -> str:
    """Search Spotify for tracks, artists, albums, or playlists.

    Args:
        query: Search query (e.g. "Bohemian Rhapsody", "artist:Queen").
        type: Comma-separated types to search: track, artist, album, playlist. Default "track".
    """
    results = _get_sp().search(q=query, limit=50, type=type)
    out = {}
    for key in results:
        items = results[key]["items"]
        if key == "tracks":
            out["tracks"] = [_format_track(t) for t in items]
        elif key == "artists":
            out["artists"] = [
                {"name": a["name"], "uri": a["uri"], "genres": a.get("genres", [])}
                for a in items
            ]
        elif key == "albums":
            out["albums"] = [
                {
                    "name": a["name"],
                    "artists": [x["name"] for x in a["artists"]],
                    "uri": a["uri"],
                    "total_tracks": a["total_tracks"],
                }
                for a in items
            ]
        elif key == "playlists":
            out["playlists"] = [
                {
                    "name": p["name"],
                    "uri": p["uri"],
                    "owner": p["owner"]["display_name"],
                    "total_tracks": (p.get("items") or p.get("tracks") or {}).get("total", 0),
                }
                for p in items
            ]
    return _json(out)


# ── Playlists ─────────────────────────────────────────────────────────


@mcp.tool()
def spotify_list_playlists() -> str:
    """List the current user's playlists (including followed playlists)."""
    sp = _get_sp()
    results = sp.current_user_playlists(limit=50)
    playlists = [
        {
            "name": p["name"],
            "id": p["id"],
            "uri": p["uri"],
            "owner": p["owner"]["display_name"],
            "total_tracks": (p.get("items") or p.get("tracks") or {}).get("total", 0),
        }
        for p in results["items"]
    ]
    return _json(playlists)


@mcp.tool()
def spotify_list_tracks(playlist_id: str) -> str:
    """List tracks in a playlist. Use "liked" to get the user's Liked Songs.

    Args:
        playlist_id: Playlist ID, URI, or URL. Use "liked" for Liked Songs.
    """
    sp = _get_sp()
    if playlist_id.lower() == "liked":
        results = sp.current_user_saved_tracks(limit=50)
        tracks = [_format_track(item["track"]) for item in results["items"] if item.get("track")]
        return _json({"source": "Liked Songs", "total": results["total"], "tracks": tracks})

    results = sp.playlist_items(playlist_id, limit=50, additional_types=("track",))
    tracks = []
    for item in results["items"]:
        t = item.get("track")
        if t is not None:
            tracks.append(_format_track(t))
    return _json({"total": results["total"], "tracks": tracks})


# ── Playback ──────────────────────────────────────────────────────────


def _pick_device(sp) -> str | None:
    """Return the active device ID, or the first available one if none is active."""
    devices = sp.devices().get("devices", [])
    for d in devices:
        if d["is_active"]:
            return None  # already active, no need to specify
    return devices[0]["id"] if devices else None


@mcp.tool()
def spotify_play(
    uri: str | None = None,
    context_uri: str | None = None,
    random: bool = False,
) -> str:
    """Start or resume playback. Provide a track URI to play a specific track,
    a context URI (album/playlist) to play a collection, or nothing to resume.
    Set random=true to play a random song from the user's Liked Songs.

    Args:
        uri: Spotify track URI to play (e.g. "spotify:track:xxx"). Omit to resume current playback.
        context_uri: Spotify album/playlist URI to play (e.g. "spotify:playlist:xxx").
        random: If true, pick and play a random track from the user's Liked Songs.
    """
    sp = _get_sp()
    device_id = _pick_device(sp)
    if random:
        total = sp.current_user_saved_tracks(limit=1)["total"]
        offset = _random.randint(0, max(total - 1, 0))
        track = sp.current_user_saved_tracks(limit=1, offset=offset)["items"][0]["track"]
        sp.start_playback(device_id=device_id, uris=[track["uri"]])
        return _json({"status": "playing", "track": _format_track(track)})
    if uri:
        sp.start_playback(device_id=device_id, uris=[uri])
    elif context_uri:
        sp.start_playback(device_id=device_id, context_uri=context_uri)
    else:
        sp.start_playback(device_id=device_id)
    return _json({"status": "playing"})


@mcp.tool()
def spotify_pause() -> str:
    """Pause the current playback."""
    _get_sp().pause_playback()
    return _json({"status": "paused"})



if __name__ == "__main__":
    mcp.run()
