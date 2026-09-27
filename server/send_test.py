import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.request

url, slack_id, kind, title = sys.argv[1:5]
project = sys.argv[5] if len(sys.argv) > 5 else None
key = os.environ["PIXL_API_KEY"].split(",")[0].encode()

body = json.dumps(
    {"id": f"test:{secrets.token_hex(8)}", "slack_ids": [slack_id], "kind": kind, "title": title, "project": project}
).encode()
ts = str(int(time.time()))
req = urllib.request.Request(
    f"{url.rstrip('/')}/webhook/pixl",
    data=body,
    headers={
        "Content-Type": "application/json",
        "x-little-guy-timestamp": ts,
        "x-little-guy-signature": hmac.new(key, ts.encode() + b"." + body, hashlib.sha256).hexdigest(),
    },
)
print(urllib.request.urlopen(req).read().decode())
