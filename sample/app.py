from flask import Flask, render_template, request
app = Flask(__name__)

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/push_notification_url', methods=['POST'])
def push_notification_url():
    """
    you will receive something like this in request.json

        {   u'type': u'message',
            u'chat_token': u'31a6e593-cccc-cccc-808c-e0bd9ea5b274',
            u'data': {  u'body': u'hello', u'status': u'connnected', u'timestamp': 1424791573.784389,
                        u'clientId': u'934cea3e-e840-4f28-a87c-0a195fb2b731',
                        u'token': u'31a6e593-cccc-cccc-808c-e0bd9ea5b274',
                        u'type': u'message'}}

    :return:
    """
    print "received...", request.json
    return 'OK'

@app.route('/profile_url')
def profile_url():
    """
    you will receive
    Authorization: Token TOKEN_9801e167-50d2-485d-b720-4558e378a580
    header in request.headers

    if user is authenticated you should return 200 here, or else return something other than
    200, hipochat will return error to client then.

    :return:
    """
    print "headers", request.headers
    return 'OK'


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8194)
