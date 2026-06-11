import urllib.request
import json
import urllib.error

req = urllib.request.Request(
    'http://localhost:8109/v1/chat',
    data=json.dumps({'model': 'llama3-70b-8192', 'messages': [{'role': 'user', 'content': 'hi'}], 'metadata': {'agent_id': 'planner'}}).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    res = urllib.request.urlopen(req)
    print("SUCCESS")
    print(res.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print('Error', e.code)
    print(e.read().decode('utf-8'))
