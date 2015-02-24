from flask import Flask, render_template
app = Flask(__name__)

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/push_notification_url')
def push_notification_url():
    return 'OK'

@app.route('/profile_url')
def profile_url():
    return 'OK'


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8194)
