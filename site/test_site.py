"""The site build: every page and link is there, agents' text is escaped, and a changed file stops the build.

Profiles are signed here with a throwaway key, the same way the publish job signs them with the real one.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import build as site
import pytest
from overshoulder import registry, sign
from overshoulder.osp import OspError

CALC = "Microsoft.WindowsCalculator_8wekyb3d8bbwe"
NOTEPAD = "Microsoft.WindowsNotepad_8wekyb3d8bbwe"
KEY_ID = "test-1"

CALC_LINES = [
    "#osp 1 made_with=Overshoulder/0.1.0.dev0",
    f'app {CALC} rev=0 ver=11.2607.0.0 "Calculator"',
    "view main window src=use n=33",
    'ctl togglepanebutton main Button aid=TogglePaneButton src=use ses=2 ver=11.2607.0.0 seen=4 ok=4 "Open Navigation"',
    "ctl listitem main ListItem name=content src=use ses=2 ver=11.2607.0.0 seen=4 ok=4",
    'ctl equalbutton main Button aid=equalButton src=use ses=2 ver=11.2607.0.0 seen=2 ok=2 "Equals"',
    "way invoke@button.uia_invoke ok=29 fail=0 src=use ms=397",
    "way select@listitem.uia_select ok=4 fail=0 src=use ms=452",
    'quirk q-fc7c6ab4a5 n=1 src=agent "Navigation pane closes itself after a mode is selected."',
    ('how h-switch-to-scientific-mode n=1 src=agent used=2 "switch to Scientific mode" : invoke Open%20Navigation ; '
    "select Scientific%20Calculator"),
]
HOSTILE = '<script>alert(1)</script> & <b>bold</b>'
NOTEPAD_LINES = [
    "#osp 1 made_with=Overshoulder/0.1.0.dev0",
    f'app {NOTEPAD} rev=0 ver=11.2507.26.0 "Notepad"',
    "view main window src=use n=17",
    "view w-popuphost dialog src=use n=2",
    ('ctl secondarybutton w-popuphost Button aid=SecondaryButton src=use ses=2 ver=11.2507.26.0 seen=2 ask=2 ok=2 '
    '"Don\'t save"'),
    "way click@button.button_message ok=0 fail=3 src=use why=next_rung",
    "way hotkey@focus.posted_keys ok=2 fail=2 src=use ms=400 why=verify_failed",
    "key ctrl+s src=use n=2",
    'key ctrl+t src=agent "new tab"',
    f'quirk q-40f3d7d5d8 n=1 src=agent "{HOSTILE}"',
    ('paint p-35d35d60d49e main src=use box=150,20,180,50 sz=200,100 dh=00ff00ff00ff00ff ver=11.2507.26.0 ses=3 hit=1 '
    '"the gear icon"'),
    'note g-5f895e8c7f url=https://support.microsoft.com/notepad-tabs n=1 src=agent "The official guide to tabs"',
]


def osp(lines: list[str]) -> bytes:
    body = "".join(line + "\n" for line in lines)
    return (body + f"end sha256={hashlib.sha256(body.encode()).hexdigest()}\n").encode()


@pytest.fixture
def key():
    return sign.private_key("11" * 32)


@pytest.fixture
def keys(key):
    return {KEY_ID: sign.public_hex(key)}


def registry_dist(tmp_path: Path, key, profiles: dict[str, bytes]) -> Path:
    """A registry checkout holding these files, built and signed the way the publish job does it."""
    root, dist = tmp_path / "repo", tmp_path / "dist"
    meta = {}
    for n, (path, data) in enumerate(profiles.items(), start=1):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
        meta[path] = registry.Published(by=path.rsplit("/", 1)[1][:-4], pr=n, at="2026-11-02", rev=1)
    (root / "apps").mkdir(parents=True, exist_ok=True)
    out = registry.build(root, dist, meta, key, KEY_ID, commit="0123456789abcdef")
    assert out["skipped"] == [], out["skipped"]
    return dist


@pytest.fixture
def dist(tmp_path, key, keys):
    d = registry_dist(tmp_path, key, {f"apps/{CALC}/yepgent.osp": osp(CALC_LINES),
                                      f"apps/{NOTEPAD}/someone.osp": osp(NOTEPAD_LINES)})
    site.build(d, keys)
    return d


def _local_refs(page: str) -> list[str]:
    return [u for u in re.findall(r'(?:href|src|poster)="([^"]+)"', page) if u.startswith("/")]


def test_every_page_and_every_local_link_is_there(dist):
    pages = sorted(dist.rglob("*.html"))
    assert {p.relative_to(dist).as_posix() for p in pages} == {
        "index.html", "404.html", f"apps/{CALC}/index.html", f"apps/{CALC}/yepgent/index.html",
        f"apps/{NOTEPAD}/index.html", f"apps/{NOTEPAD}/someone/index.html"}
    for p in pages:
        text = p.read_text("utf-8")
        assert "<script" not in text, p
        for ref in _local_refs(text):
            target = ref.split("#")[0]
            target = target + "index.html" if target.endswith("/") else target
            assert (dist / target.lstrip("/")).is_file(), f"{p.relative_to(dist)} links to {ref}"


def test_text_from_a_profile_is_escaped(dist):
    page = (dist / f"apps/{NOTEPAD}/someone/index.html").read_text("utf-8")
    assert "<script>alert(1)" not in page and "<b>bold</b>" not in page
    assert '<q class="said">&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;</q>' in page


def test_a_profile_page_says_what_it_holds_in_words(dist):
    calc = (dist / f"apps/{CALC}/yepgent/index.html").read_text("utf-8")
    assert "Reviewed on the registry, published by" in calc and "pull request #1</a> on 2 Nov 2026" in calc
    assert "Invoke on a button, through UI Automation&#x27;s invoke: worked 29 of 29." in calc
    assert "1 control (list item) named by the person's own content" in calc
    assert "<i>invoke Open Navigation</i>, then <i>select Scientific Calculator</i>. Agents have followed it 2 times." in calc
    assert 'download="calculator.osp"' in calc
    notepad = (dist / f"apps/{NOTEPAD}/someone/index.html").read_text("utf-8")
    assert "worked 0 of 3, so agents try another method first." in notepad
    assert "Hotkey on the focused control" in notepad
    assert "you were asked before agents used it" in notepad
    assert '<code>Ctrl+T</code> <q class="said">new tab</q>' in notepad
    assert 'href="https://support.microsoft.com/notepad-tabs" rel="nofollow ugc noopener noreferrer"' in notepad


def test_headers_give_every_profile_a_text_type(dist):
    rules = (dist / "_headers").read_text("utf-8")
    for path in (f"apps/{CALC}/yepgent.osp", f"apps/{NOTEPAD}/someone.osp", "index.json.sig"):
        assert f"/{path}\n  Content-Type: text/plain; charset=utf-8" in rules
    css = next(dist.glob("site.*.css")).name
    assert f"/{css}\n  Cache-Control: public, max-age=31536000, immutable" in rules
    assert "script-src" not in rules and "default-src 'none'" in rules


def test_an_empty_registry_says_so(tmp_path, key, keys):
    d = registry_dist(tmp_path, key, {})
    site.build(d, keys)
    assert "No profile has been published yet." in (d / "index.html").read_text("utf-8")


def test_a_file_changed_after_the_build_stops_the_site(dist, keys):
    f = dist / f"apps/{CALC}/yepgent.osp"
    f.write_bytes(f.read_bytes().replace(b"ok=29", b"ok=99"))
    with pytest.raises(OspError, match="does not match the catalog's hash"):
        site.build(dist, keys)


def test_a_catalog_signed_with_another_key_stops_the_site(dist):
    with pytest.raises(OspError):
        site.build(dist, {KEY_ID: sign.public_hex(sign.private_key("22" * 32))})
