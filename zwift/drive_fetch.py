#!/usr/bin/env python3
"""Save a photo downloaded with the Google Drive connector to the photos folder.

The connector's download_file_content returns JSON {content (base64), id, mimeType, title}; when the
result is large it is saved to a file and the tool result gives that file's path. This decodes it
to PHOTOS_DIR/<relative path>, converting HEIC to JPEG-readable form is left to slideshow.py
(pillow-heif is registered there if installed).

Usage:
  python3 zwift/drive_fetch.py RESULT_FILE PHOTOS_DIR "Drive/Album/Sub/name.jpg"
  python3 zwift/drive_fetch.py --ids TOPIC_ID      # print "relpath<TAB>file id" for a topic's Drive photos
  python3 zwift/drive_fetch.py --unused            # print Drive photos not used in any topic
"""
import base64, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "drive_photos.json")
TOPICS = os.path.join(HERE, "slideshows.json")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    a = sys.argv[1:]
    if a and a[0] == "--ids":
        man = load(MANIFEST)
        t = next(t for t in load(TOPICS) if t["id"] == a[1])
        for p in t["photos"]:
            if p.startswith("Drive/"):
                print(f"{p}\t{man[p]['id']}")
        return
    if a and a[0] == "--unused":
        used = {p for t in load(TOPICS) for p in t["photos"]}
        for p in load(MANIFEST):
            if p not in used:
                print(p)
        return
    if len(a) != 3:
        sys.exit(__doc__)
    src, photos, rel = a
    with open(src, encoding="utf-8") as f:
        raw = f.read()
    d = json.loads(raw)
    if isinstance(d, list):  # some clients wrap the result as [{"type":"text","text": "..."}]
        d = json.loads(d[0]["text"])
    out = os.path.join(photos, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(base64.b64decode(d["content"]))
    print(out, os.path.getsize(out))


if __name__ == "__main__":
    main()
