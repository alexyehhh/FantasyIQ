import os

# Tests never wait on the pacing of requests to ESPN (they use fake transports anyway). Set before
# anything reads the settings, which are read once.
os.environ["ESPN_MIN_REQUEST_INTERVAL_SECONDS"] = "0"
