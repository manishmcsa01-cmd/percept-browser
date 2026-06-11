import urllib.request, json
try:
    resp = urllib.request.urlopen('http://localhost:8109/v1/status')
    status = json.loads(resp.read())
    print(json.dumps(status["live"]["nvidia"], indent=2))
except Exception as e:
    print("Error:", e)
