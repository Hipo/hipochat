import os
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
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
import redis
import logging
import datetime
import calendar
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

REGULAR_MESSAGE_TYPE = os.getenv('HIPOCHAT_REGULAR_MESSAGE_TYPE', "message")
mtypes = os.getenv('HIPOCHAT_MESSAGE_TYPES', REGULAR_MESSAGE_TYPE)
MESSAGE_TYPES = mtypes.split(',')

NOTIFIABLE_MESSAGE_TYPES = os.getenv('HIPOCHAT_NOTIFIABLE_MESSAGE_TYPES', mtypes).split(',')

# some sanity checks
REDIS_CONNECTION = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
REDIS_CONNECTION.ping()

pika_connected = False
websockets = defaultdict(set)


def push_notification_callback(*args, **kwargs):
    logger.info("push notification sent")


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
        profile_dict = json.loads(response.content)
        profile_dict.update({'token': token})
    except:
        logger.exception("exception when authenticating")
        raise gen.Return(None)

    if response.code == 200:
        raise gen.Return(profile_dict)
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

        auth_token = authentication['token']
        chat_token = args[0]
        redis_client = REDIS_CONNECTION

        logout_at = redis_client.get('%s-%s-%s' % (chat_token, auth_token, 'logout_at'))
        logout_at = calendar.timegm(datetime.datetime.utcnow().timetuple()) if logout_at is None else logout_at

        redis_client.delete('%s-%s-%s' % (chat_token, auth_token, 'logout_at'))
        redis_client.set('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, chat_token, auth_token), 0)

        read_messages = redis_client.zrangebyscore(chat_token, '-inf', logout_at)
        unread_messages = redis_client.zrangebyscore(chat_token, logout_at, '+inf')

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({'read_messages': read_messages, 'unread_messages': unread_messages}))


class ItemMessageHandler(tornado.web.RequestHandler):

    @gen.coroutine
    def post(self, *args, **kwargs):
        chat_token = args[0]
        profile = yield authenticate(self.request)
        redis_client = REDIS_CONNECTION

        if not profile:
            self.clear()
            self.set_status(400)
            self.finish()
            return

        auth_token = profile['token']
        data_type = self.get_argument('type', None)
        assert data_type in MESSAGE_TYPES, '%s not in MESSAGE_TYPES' % data_type
        pika_client.declare_queue(chat_token)
        ts = calendar.timegm(datetime.datetime.utcnow().timetuple())

        if self.request.body:
            body = json.loads(self.request.body)
        else:
            body = None

        data = {'timestamp': ts, 'type': data_type, 'author': profile, 'token': chat_token}
        if body:
            data.update({'body': body})

        pika_client.sample_message(json.dumps(data))

        members = redis_client.smembers('%s-%s' % ('members', chat_token))
        members.discard(auth_token)
        for other in members:
            # Increase notification count for users other than sender
            redis_client.incr('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, chat_token, other))

        redis_client.zadd(chat_token, json.dumps(data), ts)

        if data_type in NOTIFIABLE_MESSAGE_TYPES:
            # Send push to only not connected members
            headers = {'Authorization': 'Token %s' % auth_token, 'content-type': 'application/json'}
            [members.discard(socket.authentication_token) for socket in websockets[chat_token]]

            data = {'chat_token': chat_token, 'receivers': list(members),
                    'type': data_type, 'author': profile, 'body': body}

            client = AsyncHTTPClient()
            request = HTTPRequest(PUSH_NOTIFICATION_URL, body=json.dumps(data),
                                  headers=headers, method='POST')
            client.fetch(request, callback=push_notification_callback)


class WebSocketChatHandler(tornado.websocket.WebSocketHandler):
    chat_token = None
    profile = None
    redis_client = REDIS_CONNECTION

    @gen.coroutine
    def open(self, *args, **kwargs):
        logger.info('new connection')
        self.chat_token = args[0]
        self.profile = yield authenticate(self.request, type='socket')

        if not self.profile:
            logger.info("not authenticated... !!!")
            self.clear()
            self.write_message(json.dumps(dict({"ERROR": "authentication error"})))
            self.close()
            # if client closes the connection on_close is called, if we close the connection
            # on_close is not triggered, so we call it manually.
            self.on_close()
            return

        # When user opens a connection, set notification count to 0
        self.redis_client.set('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, self.chat_token, self.profile['token']), 0)
        # add user to the channel if it's not there.
        logger.info("adding {} to channel: {}".format(self.profile['token'], self.chat_token))
        self.redis_client.sadd('%s-%s' % ('members', self.chat_token), self.profile['token'])

        pika_client.declare_queue(self.chat_token)
        pika_client.websocket = self
        websockets[self.chat_token].add(self)

    def on_message(self, message):
        ts = calendar.timegm(datetime.datetime.utcnow().timetuple())
        message_dict = json.loads(message)
        message_dict.update({'timestamp': ts, 'author': self.profile})
        self.redis_client.zadd(self.chat_token, ts, json.dumps(message_dict))

        message_dict.update({'token': self.chat_token})
        pika_client.sample_message(json.dumps(message_dict))

        members = self.redis_client.smembers('%s-%s' % ('members', self.chat_token))
        members.discard(self.profile['token'])

        for other in members:
            # Increase notification count for users other than sender
            self.redis_client.incr('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, self.chat_token, other))

        self.redis_client.set('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, self.chat_token, self.profile['token']), 0)

        if REGULAR_MESSAGE_TYPE in NOTIFIABLE_MESSAGE_TYPES:
            headers = {'Authorization': 'Token %s' % self.profile['token'], 'content-type': 'application/json'}
            [members.discard(socket.profile['token']) for socket in websockets[self.chat_token]]

            data = {
                'chat_token': self.chat_token,
                'receivers': list(members),
                'body': message_dict['body'],
                'type': REGULAR_MESSAGE_TYPE,
                'author': message_dict['author']
            }

            client = AsyncHTTPClient()
            request = HTTPRequest(PUSH_NOTIFICATION_URL, body=json.dumps(data), headers=headers, method='POST')
            client.fetch(request, callback=push_notification_callback)

    def on_close(self):
        logger.info("closing connection")
        websockets[self.chat_token].discard(self)
        ts = calendar.timegm(datetime.datetime.utcnow().timetuple())
        self.redis_client.set('%s-%s-%s' % (self.chat_token, self.profile['token'], 'logout_at'), ts)


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
        number = redis_client.get('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, chat_token, auth_token))
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


class UnsubscribeHandler(tornado.web.RequestHandler):

    def post(self, *args, **kwargs):
        # TODO: unsubscribe from rabbitmq, close socket etc...
        chat_token = args[0]
        if self.request.body_arguments.get('tokens'):
            redis_client = REDIS_CONNECTION
            data = self.request.body_arguments
            for token in data['tokens']:
                redis_client.srem('%s-%s' % ('members', chat_token), token)
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
                "unread_count": redis_client.get('%s-%s-%s' % (REGULAR_MESSAGE_TYPE, room, auth_token.get("token"))) or 0,
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
                                (r'/talk/unsubscribe/([a-zA-Z\-0-9\.:,_]+)/?', NewChatRoomHandler),
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
