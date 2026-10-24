"""Deploy dist/ to the Netlify site: one zip upload through Netlify's API, then wait until it is live.

No Netlify CLI and nothing from npm: the job that runs this also signs the registry, so it installs as
little as possible. After the deploy it fetches index.json from the live site and compares it with the
one it uploaded, so a deploy that didn't take fails the job.

    NETLIFY_AUTH_TOKEN=... NETLIFY_SITE_ID=... python site/deploy.py --dir dist
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.netlify.com/api/v1"


def zip_dir(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root).as_posix())
    return buf.getvalue()


def _call(method: str, url: str, token: str, data: bytes | None = None, ctype: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "overshoulder-profiles-deploy"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache",
                                               "User-Agent": "overshoulder-profiles-deploy"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def deploy(dist: Path, site_id: str, token: str, timeout_s: int = 300) -> dict:
    d = _call("POST", f"{API}/sites/{site_id}/deploys", token, zip_dir(dist), "application/zip")
    deadline = time.monotonic() + timeout_s
    while d.get("state") not in ("ready", "error"):
        if time.monotonic() > deadline:
            raise RuntimeError(f"deploy {d.get('id')} still {d.get('state')} after {timeout_s} s")
        time.sleep(3)
        d = _call("GET", f"{API}/deploys/{d['id']}", token)
    if d["state"] == "error":
        raise RuntimeError(f"deploy {d['id']} failed: {d.get('error_message') or 'no message'}")
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="dist")
    a = ap.parse_args(argv)
    token, site_id = os.environ.get("NETLIFY_AUTH_TOKEN", ""), os.environ.get("NETLIFY_SITE_ID", "")
    if not token or not site_id:
        print("set NETLIFY_AUTH_TOKEN and NETLIFY_SITE_ID", file=sys.stderr)
        return 2
    dist = Path(a.dir)
    d = deploy(dist, site_id, token)
    built = (dist / "index.json").read_bytes()
    # The deploy's own address, then the site's netlify.app name, which serves whatever is published.
    # Not the custom domain: until its DNS points at Netlify it answers elsewhere, or not at all.
    for live in (d["deploy_ssl_url"].rstrip("/"), f"https://{d['name']}.netlify.app"):
        for _ in range(6):
            if _get(f"{live}/index.json?deploy={d['id']}") == built:
                print(f"{live}/index.json matches the one built here")
                break
            time.sleep(5)
        else:
            print(f"{live}/index.json differs from the one built here", file=sys.stderr)
            return 1
    print(f"deploy {d['id']} is live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
