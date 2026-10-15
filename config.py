import os

def secret_key():
    # kept in a file next to the app, so logins survive a restart
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'secret_key')
    try:
        with open(path, 'rb') as f:
            return f.read()
    except FileNotFoundError:
        key = os.urandom(24)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            f.write(key)
        return key

class Config:
    SECRET_KEY = secret_key()
