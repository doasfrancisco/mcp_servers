"""Spotify client wrapper around Spotipy with OAuth token caching."""

import os
from pathlib import Path

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

_DIR = Path(__file__).parent

load_dotenv(_DIR.parent.parent / ".env")

# Scopes needed for all MCP tools
SCOPES = " ".join([
    "user-library-read",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
])


def build_client() -> spotipy.Spotify:
    """Build an authenticated Spotipy client with cached tokens."""
    cache_path = _DIR / ".spotify_token_cache"
    auth_manager = SpotifyOAuth(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
        scope=SCOPES,
        cache_handler=CacheFileHandler(cache_path=str(cache_path)),
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)
