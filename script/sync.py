#!/usr/bin/env python3
"""Sync kept tracks to a rolling YouTube Music playlist (stage 3).

Not built yet - this is the auth smoke test. See docs/playlist-sync.md.

Credentials, three pieces (none of them stdlib-obtainable, hence ytmusicapi
in requirements.txt - there is no official YouTube Music API):

- YTMUSIC_CLIENT_ID / YTMUSIC_CLIENT_SECRET: a Google Cloud OAuth client of
  type "TVs and Limited Input devices". Create one in Cloud Console, with
  the YouTube Data API enabled on the same project.
- YTMUSIC_OAUTH_JSON: the contents of the oauth.json produced by running
  `ytmusicapi oauth --client-id ... --client-secret ...` interactively, once,
  on a machine with a browser. That step logs into the target YouTube Music
  account and can't be done headlessly - do it locally, then paste the
  resulting file's contents into the GitHub secret.

oauth.json holds the refresh token, not the client id/secret - both must be
supplied again at runtime alongside it. The refresh token renews the access
token indefinitely on its own, but the refresh token itself may expire if
the Cloud project is still in "Testing" publishing status - unverified. If
this starts failing after roughly a week, that's almost certainly it; move
the project to Production in Cloud Console.
"""

import json
import os
import sys
import tempfile

from ytmusicapi import OAuthCredentials, YTMusic

OAUTH_FILE_PATH = "data/.oauth.json"  # local-only fallback, gitignored


def get_client():
    client_id = os.environ["YTMUSIC_CLIENT_ID"]
    client_secret = os.environ["YTMUSIC_CLIENT_SECRET"]
    oauth_json = os.environ.get("YTMUSIC_OAUTH_JSON")

    if oauth_json:
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        fh.write(oauth_json)
        fh.close()
        oauth_path = fh.name
    else:
        oauth_path = OAUTH_FILE_PATH

    if not os.path.exists(oauth_path):
        print(
            f"no oauth token at {oauth_path} and YTMUSIC_OAUTH_JSON not set - "
            f"run `ytmusicapi oauth --client-id ... --client-secret ... "
            f"--file {OAUTH_FILE_PATH}` locally first",
            file=sys.stderr,
        )
        sys.exit(1)

    return YTMusic(
        oauth_path,
        oauth_credentials=OAuthCredentials(client_id=client_id, client_secret=client_secret),
    )


def main():
    ytmusic = get_client()
    playlists = ytmusic.get_library_playlists(limit=25)
    print(f"authenticated - {len(playlists)} playlist(s) in this account's library:")
    for p in playlists:
        print(f"  {p['playlistId']}  {p['title']}")


if __name__ == "__main__":
    main()
