"""Spotify → website loop, independent from the legacy Telegram application."""
import configparser
import os
from pathlib import Path
import time
from .Website import WebsitePublisher,playback_payload


def run(config_path='config.ini'):
    config=configparser.ConfigParser(interpolation=None)
    if not config.read(config_path):raise SystemExit('Create config.ini from config.example.ini first.')
    publisher=WebsitePublisher.from_config(config)
    client_id=config.get('SP_AUTH','CLIENT_ID',fallback='').strip()
    if not client_id or client_id.startswith('YOUR_'):raise SystemExit('Add your Spotify application CLIENT_ID to config.ini.')
    interval=max(1,min(10,config.getfloat('GENERAL','RefreshInterval',fallback=3)))
    callback=config.get('SP_AUTH','CALLBACK_URL',fallback='http://127.0.0.1:8888/callback')
    # Lazy imports ensure Telegram-only dependencies are never imported in website mode.
    import spotipy
    from spotipy.oauth2 import SpotifyPKCE,SpotifyOAuth
    from spotipy.cache_handler import CacheFileHandler
    private=Path(config_path).resolve().parent/'.local';private.mkdir(mode=0o700,exist_ok=True)
    private.chmod(0o700)
    cache=CacheFileHandler(cache_path=str(private/'spotify-token.json'))
    options=dict(client_id=client_id,redirect_uri=callback,scope='user-read-playback-state',cache_handler=cache,open_browser=False)
    secret=config.get('SP_AUTH','CLIENT_SECRET',fallback='').strip()
    auth=SpotifyOAuth(client_secret=secret,**options) if secret and not secret.startswith('YOUR_') else SpotifyPKCE(**options)
    if not cache.get_cached_token():raise SystemExit('Connect Spotify first: python -m src.Connect')
    spotify=spotipy.Spotify(auth_manager=auth,requests_timeout=8,retries=0)
    print('Telefy: website mode. Telegram is disabled. Press Ctrl+C to stop.')
    try:
        while True:
            began=time.monotonic()
            try:
                playback=spotify.current_playback()
                publisher.publish(playback_payload(playback))
                token_path=private/'spotify-token.json'
                if token_path.exists():token_path.chmod(0o600)
            except spotipy.SpotifyException as exc:
                # A failed API call is not a stop event; the website expires stale data itself.
                print('Spotify request failed (HTTP %s); will retry.' % exc.http_status)
                if exc.http_status==429:
                    try:time.sleep(min(300,max(1,int((exc.headers or {}).get('Retry-After',30)))))
                    except ValueError:time.sleep(30)
            except (OSError,spotipy.SpotifyOauthError):
                print('Spotify authorization or connection failed; will retry.')
            time.sleep(max(.1,interval-(time.monotonic()-began)))
    except KeyboardInterrupt:
        publisher.retry_at=0
        publisher.publish(playback_payload(None))
        print('Telefy stopped.')
