"""One-time browser authorization with a validated local callback. No Telegram."""
import configparser
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs,urlparse


def main():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth,SpotifyPKCE
    from spotipy.cache_handler import CacheFileHandler
    config=configparser.ConfigParser(interpolation=None);config.read('config.ini')
    private=Path('.local');private.mkdir(mode=0o700,exist_ok=True);private.chmod(0o700)
    callback=config.get('SP_AUTH','CALLBACK_URL',fallback='http://127.0.0.1:8888/callback')
    parts=urlparse(callback)
    if parts.scheme!='http' or parts.hostname!='127.0.0.1':raise SystemExit('Use a 127.0.0.1 HTTP callback for this local setup.')
    nonce=secrets.token_urlsafe(32)
    options=dict(client_id=config.get('SP_AUTH','CLIENT_ID'),redirect_uri=callback,scope='user-read-playback-state',state=nonce,cache_handler=CacheFileHandler(cache_path=str(private/'spotify-token.json')),open_browser=False)
    secret=config.get('SP_AUTH','CLIENT_SECRET',fallback='').strip()
    auth=SpotifyOAuth(client_secret=secret,**options) if secret else SpotifyPKCE(**options)
    result={}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed=urlparse(self.path);q=parse_qs(parsed.query)
            if parsed.path!=parts.path:self.send_error(404);return
            if not secrets.compare_digest(q.get('state',[''])[0],nonce):self.send_error(400,'Invalid OAuth state');return
            result['code']=q.get('code',[None])[0];result['error']=q.get('error',[None])[0]
            content='<html lang="ru"><meta charset="utf-8"><title>Telefy</title><body style="background:#050505;color:#eee;font:18px system-ui;padding:10vh 10vw">Ответ Spotify получен. Можно вернуться в Codex.</body></html>'.encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',parts.port or 80),Handler);server.timeout=1
    print('Open this Spotify authorization URL:',flush=True)
    print(auth.get_authorize_url(state=nonce),flush=True)
    deadline=time.monotonic()+900
    while not result and time.monotonic()<deadline:server.handle_request()
    server.server_close()
    if not result.get('code'):raise SystemExit('Authorization not completed.')
    try:auth.get_access_token(code=result['code'],check_cache=False)
    except spotipy.SpotifyOauthError:raise SystemExit('Spotify did not accept the authorization. Check application credentials and callback URL.')
    (private/'spotify-token.json').chmod(0o600)
    print('Spotify connected. Start: python -m src --mode website',flush=True)

if __name__=='__main__':main()
