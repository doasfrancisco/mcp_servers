"""Simple test script — search Spotify for a track using client credentials."""

import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Reads SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET from env
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials())

query = "Bohemian Rhapsody"
results = sp.search(q=query, limit=5, type="track")

print(f"Search results for: {query}\n")
for i, track in enumerate(results["tracks"]["items"]):
    artists = ", ".join(a["name"] for a in track["artists"])
    album = track["album"]["name"]
    print(f"  {i+1}. {track['name']}")
    print(f"     Artist(s): {artists}")
    print(f"     Album:     {album}")
    print(f"     URI:       {track['uri']}")
    print()
