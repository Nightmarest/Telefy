import os
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import configparser

from src import Helper
from src.platform_utils import CONFIG_PATH, PROJECT_ROOT

config_file = str(CONFIG_PATH)
if not CONFIG_PATH.exists():
    Helper.CreateConfig()
cp = configparser.ConfigParser()
cp.read(config_file)
client_id = cp['SP_AUTH']['CLIENT_ID']
client_secret = cp['SP_AUTH']['CLIENT_SECRET']
RInterval = cp['GENERAL']['RefreshInterval']
time.sleep(float(RInterval))
AT = None

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id,
                                               client_secret=client_secret,
                                               redirect_uri='https://apicluster.ru/call',
                                               scope='user-read-playback-state',
                                               open_browser=False,
                                               cache_path=str(PROJECT_ROOT / '.spotify_token_cache')))
artist_cache = {}

def spotify_callback():
    global AT
    try:
        current_track = sp.current_playback()

        if current_track is not None:
            track_name = current_track['item']['name']
            artists_raw = current_track['item']['artists']
            duration_ms = current_track['item']['duration_ms']
            progress_ms = current_track['progress_ms']
            album_art = current_track['item']['album']['images'][0]['url']
            track_id = current_track['item']['id']

            duration_min = duration_ms // 60000
            duration_sec = (duration_ms // 1000) % 60
            progress_min = progress_ms // 60000
            progress_sec = (progress_ms // 1000) % 60
            artists = []
            for artist in artists_raw:
                artist_name = artist['name']
                artist_id = artist.get('id')
                artist_url = artist.get('external_urls', {}).get('spotify', '')
                artist_image = None
                if artist_id and artist_id in artist_cache:
                    artist_image = artist_cache[artist_id]
                elif artist_id:
                    try:
                        artist_data = sp.artist(artist_id)
                        if artist_data.get('images'):
                            artist_image = artist_data['images'][0]['url']
                            artist_cache[artist_id] = artist_image
                    except Exception:
                        artist_image = None
                artists.append({
                    'name': artist_name,
                    'id': artist_id or '',
                    'url': artist_url,
                    'image': artist_image or album_art,
                })
            ListenNow = {}
            ListenNow['AT'] = (f'{artists_raw[0]["name"]} - {track_name}')
            ListenNow['TrackName'] = track_name
            ListenNow['TT'] = (f'{duration_min}:{duration_sec:02d}')
            ListenNow['TN'] = (f'{progress_min}:{progress_sec:02d}')
            ListenNow['DurationMS'] = duration_ms
            ListenNow['ProgressMS'] = progress_ms
            ListenNow['TA'] = album_art
            ListenNow['State'] = current_track['is_playing']
            ListenNow['TrackID'] = track_id
            ListenNow['Artists'] = artists

            if AT != ListenNow['AT']:
                AT = ListenNow['AT']
                print(f"Сейчас играет: {ListenNow['AT']}")
            else:
                pass
            return ListenNow
        else:
            return None
    except Exception as e:
        print(f"Ошибка в получении данных - {e}")

        return None
