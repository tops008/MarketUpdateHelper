from flask import Flask, request
import threading
import urllib.request
from time import sleep

app = Flask(__name__)
status=0
code=""

@app.route('/')
def index():
    global code
    code=request.args.get('code','none')
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return str(code)

@app.route('/check')
def check():
    global status
    status=1
    print('status_from_check:',status)
    return str(status)

@app.route('/shutdown', methods=['GET','POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return 'Server shutting down...'

def shutdown_server():
    urllib.request.urlopen('http://localhost:80/shutdown')

def run_server():
    app.run(port=80)

def check_server():
    global status
    status=0
    urllib.request.urlopen('http://localhost:80/check')
    return status

def get_code():
    global code
    return code

def test_code():
    urllib.request.urlopen('http://localhost:80/?code=mycode')
    

if __name__ == '__main__':

    thread = threading.Thread(target=run_server)
    thread.start()
    n_tries = 0
    while check_server() == 0:
        print("Attempt #",n_tries)
        sleep(0.1)
        n_tries += 1

    test_code()
    print('code from main:',code)

    shutdown_server()
    thread.join()
    print('exiting cleanly')
    
    
