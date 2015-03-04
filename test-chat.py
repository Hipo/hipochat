import websocket
import unittest
from multiprocessing import Process
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import time
import os
import json
import redis
import requests
os.environ['HIPOCHAT_PUSH_NOTIFICATION_URL'] = "http://localhost:8194/push_notification_url"
os.environ['HIPOCHAT_PROFILE_URL'] = "http://localhost:8194/profile_url"
os.environ['HIPOCHAT_REDIS_DB'] = "3"

import hipochat.chat
import json
from urlparse import urljoin

BASE_URL = "http://127.0.0.1:8888/"


def get_headers(token):
    return {
        'Authorization': "Token {}".format(token),
        'Content-type': 'application/json',
    }


class TestChat(unittest.TestCase):

    def setUp(self):
        self.redis_conn = redis.StrictRedis(db=3)
        self.redis_conn.flushdb()
        self.process = Process(target=hipochat.chat.run)
        self.process.start()
        time.sleep(2)

    def test_client(self):
        # websocket.enableTrace(True)
        ws = websocket.create_connection("ws://127.0.0.1:8888/talk/chat/room_hipo/?token=TOKEN_1234")
        # TODO: wait until authorization
        time.sleep(2)
        d = json.dumps(dict(
            body="hello world",
            type="message"

        ))
        ws.send(d)
        result = ws.recv()
        ws.close()
        resp = requests.get(
            'http://127.0.0.1:8888/talk/history/room_hipo,room_foo?token=TOKEN_1234'
        )
        data = json.loads(resp.content)
        assert data['results'][0]['messages'][0]["body"] == "hello world"
        assert len(data['results'][1]["messages"]) == 0

    def test_kick(self):

        ROOM_FOR_KICK = "letskick"

        ws_thor = websocket.create_connection("ws://127.0.0.1:8888/talk/chat/{}/?token=thor".format(ROOM_FOR_KICK))
        # TODO: wait until authorization
        time.sleep(2)
        d = json.dumps(dict(
            body="thor is here.",
            type="message"
        ))
        ws_thor.send(d)

        ws = websocket.create_connection("ws://127.0.0.1:8888/talk/chat/{}/?token=marine".format(ROOM_FOR_KICK))
        # TODO: wait until authorization
        time.sleep(2)
        d = json.dumps(dict(
            body="go go go!",
            type="message"
        ))
        ws.send(d)
        ws.close()

        # inject a kick item
        base_url = urljoin(BASE_URL, "talk/item/" + ROOM_FOR_KICK + "/")
        item_data = {
            "action": "kick",
            "token_to_kick": "thor",
            "body": "thor has left the chat.",
            "type": "system_message",
            "token": ROOM_FOR_KICK,
        }

        headers = get_headers("thor")

        r = requests.post(base_url, headers=headers, data=json.dumps(item_data))

        assert r.status_code, 200

        ws_thor.recv()
        ws_thor.recv()
        ws_thor.recv()

        self.assertFalse( self.redis_conn.sismember("thor", "members-{}".format(ROOM_FOR_KICK)))
        self.assertRaises(websocket.WebSocketConnectionClosedException, ws_thor.recv)

    def tearDown(self):
        self.process.terminate()

if __name__ == '__main__':
    unittest.main()