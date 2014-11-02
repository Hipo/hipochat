****************************************
HIPOCHAT: Websocket chat server
****************************************

Supports notifications and keep the old messages

Hipochat is an open-source websocket chat server, using RabbitMQ as message queue, Tornado as Backend Server and
Redis for persistent data.

Keeps the notifications count and also supports injections from external server directly to websocket
Supports checking authentication with your own webserver.


How it works
======================================================

First clone the project

**git clone https://github.com/Hipo/hipochat.git**


Then install the requirements

**pip install -r requirements.txt**


Make sure that you have redis-server and rabbitmq servers are running
Set your variables in 

vars.py::

    PushNotificationURL = '<ENDPOINT RECEIVES YOUR PUSH NOTIFICATION SIGNAL AND SEND AN PN>'
    ProfileURL = '<ENDPOINT YOU CAN ASK IF USER IS AUTHENTICATED>'
    RABBIT_URL = '<RABBITMQ SERVER>'
    RABBIT_USERNAME = '<RABBITMQ USERNAME>'
    RABBIT_PASS = '<RABBITMQ PASSWORD>'


You can check the nginx reverse proxy details

Technical Detail
===================================================

Chat Server Endpoint
---------------------

Your backend server needs an EP that you should be able to create a chat room or receive the chat room tokens


Example request::

    HEADER: Authentication: Token <Token>
    URLs: **/api/chat**

Example response::

    {
        "chat": {
            "token": "e598c2a9-317a-4577-8cbd-7fd5f0cddbdf"
        }
    }


If room is created you should receive '201 CREATED' MESSAGE else if exists '200 OK'
200 OK means you already have this chat room and you should fetch the old messages


Receive the old messages
-----------------------------------------

You visit the url with parameters below


Example Request::

    HEADER -> Authorization: Token <token>
    HTTP GET **/talk/old/<chat_room_token>/**


Response::

    HTTP 200 OK

    {
    oldy: [
            {
                timestamp: 1414768486.196569,
                message: "asdasda",
                author: "asdasda"
            },
            {
                timestamp: 1414770934.580683,
                message: "adsadsdasads",
                author: "assaddsa"
            },
            {
                timestamp: 1414772188.836509,
                message: "dsadasads",
                author: "dssdaasd"
            },
            {
                timestamp: 1414773038.058612,
                token: "ac9e8485-8120-4cdc-a5c7-2687a04f01b5",
                injected: {
                       message: "hede",
                       hodo: "hede"
                }
            }
          ]
    }



As an authenticated user you can post injections to CHAT server
------------------------------------------------

You can inject external messages from a Backend Server directly into Websocket

Example Request::

    HEADER -> Authorization: Token <token>
    HTTP POST **/talk/item/<chat_room_token>/**

    {   message: "foobar",
        user: "johndoe"
    }


Start the Live Chat Server
--------------------------------------------------------

Chat Server works with websocket technology
Also you will see the injections in chat dialogue when an injection comes directly to Chat Server
You should pass the user authentication token as query parameter

Example Request::

    WEBSOCKET
    ws://server.url/talk/chat/<chat_token>/?token=<auth_token>


NOTIFICATIONS COUNT
-----------------------------------------------------

You can receive the notifications count of chat rooms for authenticated user
by sending a request like below

    HTTP GET **/talk/notification/<chat_token>/?type=<type>**
