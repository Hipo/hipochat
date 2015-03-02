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



def run_flask_app():
    from sample.app import app
    app.run(debug=False, host="0.0.0.0", port=8194)

class TestChat(unittest.TestCase):

    def setUp(self):
        self.redis_conn = redis.StrictRedis(db=3)
        self.redis_conn.flushdb()

        self.process_app = Process(target=run_flask_app)
        self.process_app.start()
        time.sleep(2)

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

        d = json.dumps(dict(
            body="hello 2222",
            type="message"

        ))
        ws.send(d)

        result = ws.recv()
        print "result --- ", result
        ws.close()

        resp = requests.get(
            'http://127.0.0.1:8888/talk/history/room_hipo,room_foo?token=TOKEN_1234'
        )
        data = json.loads(resp.content)
        self.assertEquals(data['results'][0]['messages'][0]["body"], "hello 2222")
        self.assertEquals(len(data['results'][1]["messages"]), 0)

        ws = websocket.create_connection("ws://127.0.0.1:8888/talk/chat/room_hipo/?token=TOKEN_5555")
        time.sleep(5)
        d = json.dumps(dict(
            body="hello world 3333",
            type="message"

        ))
        ws.send(d)

        d = json.dumps(dict(
            body="hello 4444",
            type="message"

        ))
        ws.send(d)

        ws.close()

        resp = requests.get(
            'http://127.0.0.1:8888/talk/old/room_hipo?token=TOKEN_1234'
        )
        data = json.loads(resp.content)

        print "================================"
        print "un......"
        print data['results']['unread_messages'][0]
        print "================================"
        self.assertEquals(data['results']['read_messages'][0]["body"], "hello 2222")
        self.assertEquals(data['results']['unread_messages'][0]["body"], "hello 4444")


    def tearDown(self):
        self.process.terminate()
        self.process_app.terminate()

if __name__ == '__main__':
    unittest.main()