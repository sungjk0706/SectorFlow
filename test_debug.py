import urllib.request
import json
req = urllib.request.Request("http://127.0.0.1:8000/api/settings")
with urllib.request.urlopen(req) as response:
    print(response.read().decode('utf-8'))
