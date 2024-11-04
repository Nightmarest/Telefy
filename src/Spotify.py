import os
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import configparser

from src import Helper

config_file = 'config.ini'
if not os.path.exists(config_file):
    Helper.CreateConfig()
cp = configparser.ConfigParser()
cp.read(config_file)
client_id = cp['SP_AUTH']['CLIENT_ID']
client_secret = cp['SP_AUTH']['CLIENT_SECRET']
RInterval = cp['GENERAL']['RefreshInterval']
time.sleep(float(RInterval))

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=client_id,
                                               client_secret=client_secret,
                                               redirect_uri='https://burmlda.apicluster.ru/call',
                                               scope='user-read-playback-state'))
def spotify_callback():
    try:
        current_track = sp.current_playback()

        if current_track is not None:
            track_name = current_track['item']['name']
            artist_name = current_track['item']['artists'][0]['name']
            duration_ms = current_track['item']['duration_ms']
            progress_ms = current_track['progress_ms']
            album_art = current_track['item']['album']['images'][0]['url']

            duration_min = duration_ms // 60000
            duration_sec = (duration_ms // 1000) % 60
            progress_min = progress_ms // 60000
            progress_sec = (progress_ms // 1000) % 60
            ListenNow = {}
            ListenNow['AT'] = (f'{artist_name} - {track_name}')
            ListenNow['TT'] = (f'{duration_min}:{duration_sec:02d}')
            ListenNow['TN'] = (f'{progress_min}:{progress_sec:02d}')
            ListenNow['TA'] = album_art
            ListenNow['State'] = current_track['is_playing']

            return ListenNow
        else:
            return None
    except Exception:
        return None


