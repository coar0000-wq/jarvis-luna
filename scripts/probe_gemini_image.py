import json, os, urllib.request, urllib.error
key = os.environ["GEMINI_API_KEY"]
def call(url, payload=None):
    req = urllib.request.Request(url, data=(json.dumps(payload).encode() if payload else None),
        headers={"Content-Type": "application/json"}, method="POST" if payload else "GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
s, b = call(f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}")
names = [m["name"] for m in b.get("models", [])] if s == 200 else []
print("list status", s, "models", len(names))
img = [n for n in names if "image" in n or "imagen" in n]
print("image-capable candidates:", img)
for n in img[:6]:
    mid = n.split("/", 1)[1]
    if "imagen" in mid:
        s, b = call(f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:predict?key={key}",
                    {"instances": [{"prompt": "a plain white bottle on a white background, studio photo"}], "parameters": {"sampleCount": 1}})
        ok = s == 200 and bool(b.get("predictions"))
    else:
        s, b = call(f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:generateContent?key={key}",
                    {"contents": [{"parts": [{"text": "A plain white bottle on a white background, studio product photo"}]}],
                     "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
        parts = (((b.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        ok = s == 200 and any("inlineData" in p or "inline_data" in p for p in parts)
    msg = "" if ok else (b.get("error", {}).get("message", "")[:160] if isinstance(b, dict) else "")
    print(mid, "HTTP", s, "image_ok", ok, msg)
