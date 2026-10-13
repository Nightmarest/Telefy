"""Optional website output. No Telegram, tray or Windows dependencies."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


def playback_payload(playback,observed_at_ms=None):
    observed_at_ms=round(time.time()*1000) if observed_at_ms is None else observed_at_ms
    result={'is_playing':False,'progress_ms':0,'observed_at_ms':observed_at_ms,'track':None}
    item=(playback or {}).get('item') or {}
    device=(playback or {}).get('device') or {}
    if device.get('is_private_session') or item.get('type')!='track' or not item.get('id') or item.get('is_local'):
        return result
    images=(item.get('album') or {}).get('images') or []
    result.update(is_playing=bool(playback.get('is_playing')),progress_ms=playback.get('progress_ms') or 0,track={
        'id':item['id'],'name':item['name'],'artists':[a['name'] for a in item.get('artists',[])],
        'duration_ms':item['duration_ms'],'cover_url':images[0]['url'] if images else ''})
    return result


class WebsitePublisher:
    def __init__(self,endpoint,token,opener=urllib.request.urlopen):
        parts=urllib.parse.urlparse(endpoint)
        if parts.scheme!='https' and not (parts.scheme=='http' and parts.hostname in ('127.0.0.1','localhost','::1')):
            raise ValueError('Website endpoint must use HTTPS, except for localhost')
        if not token:raise ValueError('Set WEBSITE Token or TELEFY_PUSH_TOKEN')
        self.endpoint=endpoint;self.token=token;self.opener=opener;self.retry_at=0
    @classmethod
    def from_config(cls,config):
        return cls(config.get('WEBSITE','Endpoint'),os.getenv('TELEFY_PUSH_TOKEN') or config.get('WEBSITE','Token',fallback=''))
    def publish(self,payload):
        if time.monotonic()<self.retry_at:return False
        request=urllib.request.Request(self.endpoint,data=json.dumps(payload).encode(),method='POST',headers={
            'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with self.opener(request,timeout=4) as response:response.read()
            return True
        except urllib.error.HTTPError as exc:
            try:delay=max(3,int(exc.headers.get('Retry-After','10')))
            except (TypeError,ValueError):delay=10
            self.retry_at=time.monotonic()+min(delay,300)
            print('Website update failed (HTTP %s); will retry.' % exc.code)
        except (OSError,urllib.error.URLError):
            self.retry_at=time.monotonic()+5
            print('Website unavailable; will retry.')
        return False
