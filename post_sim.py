import json, urllib.request
with open('/tmp/sim_payload.json','r',encoding='utf-8') as f:
    data = f.read().encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:8080/api/simconfig', data=data, headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode())
