import json
import requests
import time
import pika

from _collections import defaultdict
import tornado.ioloop
import tornado.web
import tornado.websocket
from tornado import gen
from pika.adapters.tornado_connection import TornadoConnection
import os
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


PUSH_NOTIFICATION_URL = os.getenv('HIPOCHAT_PUSH_NOTIFICATION_URL', None)
if not PUSH_NOTIFICATION_URL:
    raise Exception('we need a push notification url, please pass environment variable: HIPOCHAT_PUSH_NOTIFICATION_URL')

PROFILE_URL = os.getenv('HIPOCHAT_PROFILE_URL', None)
if not PROFILE_URL:
    raise Exception('we need a push notification url, please pass environment variable: HIPOCHAT_PROFILE_URL')

RABBIT_URL = os.getenv('HIPOCHAT_RABBIT_URL', None)
if not PROFILE_URL:
    raise Exception('we need a push notification url, please pass environment variable: HIPOCHAT_RABBIT_URL')

RABBIT_USERNAME = os.getenv('HIPOCHAT_RABBIT_USERNAME', 'guest')
RABBIT_PASS = os.getenv('HIPOCHAT_RABBIT_PASS', 'guest')

REDIS_HOST = os.getenv('HIPOCHAT_REDIS_HOST', 'localhost')
REDIS_PORT = os.getenv('HIPOCHAT_REDIS_PORT', 6379)
REDIS_DB = os.getenv('HIPOCHAT_REDIS_DB', 0)

PORT = os.getenv('HIPOCHAT_LISTEN_PORT', 8888)
ADDRESS = os.getenv('HIPOCHAT_LISTEN_ADDRESS', '0.0.0.0')


# some sanity checks
import redis
REDIS_CONNECTION = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
REDIS_CONNECTION.ping()

pika_connected = False
websockets = defaultdict(set)


class PikaClient(object):

    def __init__(self, io_loop):
        self.connected = False
        self.connecting = False
        self.connection = None
        self.channel = None
        self.ioloop = io_loop

    def connect(self):

        if self.connecting:
                logger.info('PikaClient: Already connecting to RabbitMQ')
                return

        logger.info('PikaClient: Connecting to RabbitMQ on port 5672, Object: %s', self)

        self.connecting = True

        credentials = pika.PlainCredentials(RABBIT_USERNAME, RABBIT_PASS)
        param = pika.ConnectionParameters(host=RABBIT_URL,
                                          port=5672,
                                          virtual_host="/",
                                          credentials=credentials)
        self.connection = TornadoConnection(param,
                                            on_open_callback=self.on_connected)

        global pika_connected
        pika_connected = True

    def on_connected(self, connection):
        logger.info('PikaClient: Connected to RabbitMQ on :5672')
        self.connected = True
        self.connection = connection
        self.connection.channel(self.on_channel_open)

    def on_channel_open(self, channel):
        logger.info('PikaClient: Channel Open, Declaring Exchange, Channel ID: %s', channel)
        self.channel = channel

        self.channel.exchange_declare(exchange='tornado',
                                      type="direct",
                                      durable=False,
                                      auto_delete=True)

    def declare_queue(self, token):
        logger.info('PikaClient: Exchange Declared, Declaring Queue')
        self.queue_name = token
        self.channel.queue_declare(queue=self.queue_name,
                                   durable=False,
                                   auto_delete=True,
                                   callback=self.on_queue_declared)

    def on_queue_declared(self, frame):
        self.channel.queue_bind(exchange='tornado',
                                queue=self.queue_name,
                                routing_key=self.queue_name,
                                callback=self.on_queue_bound)

    def on_queue_bound(self, frame):
        logger.info('PikaClient: Queue Bound, Issuing Basic Consume')
        self.channel.basic_consume(consumer_callback=self.on_pika_message,
                                   queue=self.queue_name,
                                   no_ack=True)

    def on_pika_message(self, channel, method, header, body):
        logger.info('PikaCient: Message receive, delivery tag #%i', method.delivery_tag)
        message = json.loads(body)
        # TODO: decrement unread count
        for i in websockets[message['token']]:
            try:
                i.write_message(body)
            except:
                logger.exception("exception while writing message to client")

    def on_basic_cancel(self, frame):
        logger.info('PikaClient: Basic Cancel Ok')
        # If we don't have any more consumer processes running close
        self.connection.close()

    def on_closed(self, connection):
        # We've closed our pika connection so stop the demo
        self.ioloop.IOLoop.instance().stop()

    def sample_message(self, ws_msg):
        token = json.loads(ws_msg)['token']
        properties = pika.BasicProperties(
            content_type="text/plain", delivery_mode=1)
        self.channel.basic_publish(exchange='tornado',
                                   routing_key=token,
                                   body=ws_msg,
                                   properties=properties)

@gen.coroutine
def authenticate(request, **kwargs):
    if kwargs.get('type') != 'socket' and request.headers.get('Authorization'):
        token = request.headers.get('Authorization').split('Token ')[1]
    elif request.arguments.get('token'):
        token = request.arguments.get('token')[0]
    else:
        raise gen.Return(None)

    headers = {'Authorization': 'Token %s' % token}
    ac = AsyncHTTPClient()
    try:
        response = yield ac.fetch(PROFILE_URL, headers=headers)
    except:
        logger.exception("exception when authenticating")
        raise gen.Return(None)

    if response.code == 200:
        raise gen.Return({'token': token})
    else:
        raise gen.Return(None)


class IndexHandler(tornado.web.RequestHandler):

    @tornado.web.asynchronous
    def get(self, *args, **kwargs):
        self.render("index.html")


class OldMessagesHandler(tornado.web.RequestHandler):

    @gen.coroutine
    def get(self, *args, **kwargs):
        authentication = yield authenticate(self.request)
        if not authentication:
            self.clear()
            self.set_status(400)
            self.finish()
            return

        auth_token = authentication.get('token')
        chat_token = args[0]
        redis_client = REDIS_CONNECTION
        oldy = redis_client.zrange(chat_token, 0, -1, withscores=True)
        redis_client.set('%s-%s-%s' % ('message', chat_token, auth_token), 0)
        redis_client.set('%s-%s-%s' % ('item', chat_token, auth_token), 0)

        new_oldy = []
        for i in  oldy:
            data = json.loads(i[0])
            data['timestamp'] = i[1]
            new_oldy.append(data)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({'oldy': new_oldy}))


class ItemMessageHandler(tornado.web.RequestHandler):

    @gen.coroutine
    def post(self, *args, **kwargs):
        chat_token = args[0]
        authentication = yield authenticate(self.request)
        if not authentication:
            self.clear()
            self.set_status(400)
            self.finish()
            return

        auth_token = authentication.get('token')
        pika_client.declare_queue(chat_token)
        redis_client = REDIS_CONNECTION
        pika_client.sample_message(self.request.body)
        members = redis_client.smembers('%s-%s' % ('members', chat_token))
        members.discard(auth_token)
        for other in members:
            # INCREASE THE NOTIFICATION COUNT FOR USERS OTHER THAN CURRENT USER
            redis_client.incr('%s-%s-%s' % ('message', chat_token, other))
        # TODO: timezone unaware
        ts = time.time()
        redis_client.zadd(chat_token, ts, self.request.body)


class WebSocketChatHandler(tornado.websocket.WebSocketHandler):

    @gen.coroutine
    def open(self, *args, **kwargs):
        logger.info('new connection')
        self.chat_token = args[0]
        authentication = yield authenticate(self.request, type='socket')
        if not authentication:
            self.authentication_token = None
            logger.info("not authenticated... !!!")
            self.clear()
            self.write_message(json.dumps(dict({"ERROR": "authentication error"})))
            self.close()
            self.on_close()
            return

        self.authentication_token = authentication.get('token', None)
        self.redis_client = REDIS_CONNECTION

        # WHEN USER OPENS A CONNECTION SET NOTIFICATIONS TO 0
        self.redis_client.set('%s-%s-%s' % ('message', self.chat_token, self.authentication_token), 0)
        self.redis_client.set('%s-%s-%s' % ('item', self.chat_token, self.authentication_token), 0)

        # add user to the channel if it's not there.
        logger.info("adding {} to channel: {}".format(self.authentication_token, self.chat_token))
        self.redis_client.sadd('%s-%s' % ('members', self.chat_token), self.authentication_token)

        pika_client.declare_queue(self.chat_token)
        pika_client.websocket = self
        websockets[self.chat_token].add(self)

    def push_message_sent(self, *args, **kwargs):
        logger.info("push message sent")

    def on_message(self, message):
        self.redis_client = REDIS_CONNECTION
        r = self.redis_client
        ts = time.time()
        message_dict = json.loads(message)
        message_dict.update({'timestamp': ts})
        r.zadd(self.chat_token, ts, json.dumps(message_dict))
        message_dict.update({'token': self.chat_token})
        pika_client.sample_message(json.dumps(message_dict))

        # GET THE OTHER USERS OTHER THAN THE CURRENT
        members = self.redis_client.smembers('%s-%s' % ('members', self.chat_token))
        members.discard(self.authentication_token)

        for other in members:
            # INCREASE THE NOTIFICATION COUNT FOR USERS OTHER THAN CURRENT USER
            self.redis_client.incr('%s-%s-%s' % ('message', self.chat_token, other))

        headers = {'Authorization': 'Token %s' % self.authentication_token, 'content-type': 'application/json'}
        [members.discard(socket.authentication_token) for socket in websockets[self.chat_token]]

        data = {'chat_token': self.chat_token,
                'receivers': list(members),
                'body': message_dict['body'],
                'type': 'message',
                'author_id': message_dict.get('author', None)}

        client = AsyncHTTPClient()
        request = HTTPRequest(PUSH_NOTIFICATION_URL, body=json.dumps(data), headers=headers, method='POST')
        client.fetch(request, callback=self.push_message_sent)

    def on_close(self):
        logger.info("closing connection")
        websockets[self.chat_token].discard(self)


class NotificationHandler(tornado.web.RequestHandler):

    @gen.coroutine
    def get(self, *args, **kwargs):
        auth_token = yield authenticate(self.request)
        if not auth_token:
            self.set_status(403)
            self.finish()

        auth_token = auth_token.get('token')
        chat_token = args[0]
        redis_client = REDIS_CONNECTION
        number = redis_client.get('%s-%s-%s' % ("message", chat_token, auth_token))
        self.write(json.dumps({'notification': number}))


class NewChatRoomHandler(tornado.web.RequestHandler):

    # SEND THE CHAT ROOM USERS ARRAY
    def post(self, *args, **kwargs):
        chat_token = args[0]
        if self.request.body_arguments.get('tokens'):
            redis_client = REDIS_CONNECTION
            data = self.request.body_arguments
            for token in data['tokens']:
                redis_client.sadd('%s-%s' % ('members', chat_token), token)
            self.clear()
            self.set_status(200)
            self.finish()
        else:
            self.set_status(400)
            self.finish()


class HistoryHandler(tornado.web.RequestHandler):

    @gen.coroutine
    def get(self, room_list):

        auth_token = yield authenticate(self.request)
        if not auth_token:
            self.set_status(403)
            self.finish()

        # get latest message if ?limit=N is not provided.
        limit = int(self.get_argument("limit", 0))
        if limit > 0:
            limit -= 1

        redis_client = REDIS_CONNECTION
        content = []
        for room in room_list.split(','):
            room_data = {
                "room_name": room,
                "messages": [],
            }

            room_history = redis_client.zrange(room, 0, limit, withscores=True)
            for i in room_history:
                data = json.loads(i[0])
                data['timestamp'] = int(i[1])
                room_data["messages"].append(data)
            content.append(room_data)

        content = {"results": content}

        self.set_status(200)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(content))
        self.finish()



app = tornado.web.Application([(r'/talk/chat/([a-zA-Z\-0-9\.:,_]+)/?', WebSocketChatHandler),
                               (r'/talk/item/([a-zA-Z\-0-9\.:,_]+)/?', ItemMessageHandler),
                               (r'/talk/notification/([a-zA-Z\-0-9\.:,_]+)/?', NotificationHandler),
                               (r'/talk/new-chat-room/([a-zA-Z\-0-9\.:,_]+)/?', NewChatRoomHandler),
                               (r'/talk/old/([a-zA-Z\-0-9\.:,_]+)/?', OldMessagesHandler),
                               (r'/talk/history/([a-zA-Z\-0-9\.:,_]+)/?', HistoryHandler),
                               (r'/talk/?', IndexHandler)])

pika_client = None


def run():
    global pika_client
    logger.info("Listening to %s:%s", ADDRESS, PORT)
    app.listen(PORT, ADDRESS)
    ioloop = tornado.ioloop.IOLoop.instance()
    pika_client = PikaClient(ioloop)
    pika_client.connect()
    ioloop.start()
