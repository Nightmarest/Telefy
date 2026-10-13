import configparser
import sys
import unittest
from src.Website import WebsitePublisher,playback_payload

class WebsiteTests(unittest.TestCase):
    def track(self):return {'is_playing':True,'progress_ms':3456,'item':{'type':'track','id':'A'*22,'name':'Title','duration_ms':150000,'artists':[{'name':'Artist'}],'album':{'images':[{'url':'https://i.scdn.co/image/example'}]}}}
    def test_payload_preserves_precision(self):
        p=playback_payload(self.track(),12345)
        self.assertEqual(p['track']['id'],'A'*22);self.assertEqual(p['progress_ms'],3456);self.assertEqual(p['observed_at_ms'],12345)
    def test_empty_private_local_and_episode(self):
        self.assertIsNone(playback_payload(None)['track'])
        for mutate in [lambda p:p.update(device={'is_private_session':True}),lambda p:p['item'].update(type='episode'),lambda p:p['item'].update(is_local=True)]:
            p=self.track();mutate(p);self.assertIsNone(playback_payload(p)['track'])
    def test_https_outside_loopback(self):
        with self.assertRaises(ValueError):WebsitePublisher('http://example.com/api/telefy','test')
        WebsitePublisher('http://127.0.0.1:50888/api/telefy','test')
    def test_website_entry_does_not_import_telegram(self):
        from src import NowPlaying
        for mod in ['telebot','pystray','win32gui','src.Helper','src.Startup']:self.assertNotIn(mod,sys.modules)
    def test_sender_network_failure_is_nonfatal(self):
        def failing(*args,**kwargs):raise OSError('offline')
        sender=WebsitePublisher('http://127.0.0.1:50888/api/telefy','test',opener=failing)
        self.assertFalse(sender.publish(playback_payload(None)))

if __name__=='__main__':unittest.main()
