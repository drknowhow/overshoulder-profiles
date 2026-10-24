"""Build overshoulder.yepgent.com from the signed registry in dist/.

Runs after `python -m overshoulder.registry build` on every merge to main. It checks the catalog's
signature and every profile's signature with the key Overshoulder ships, then writes plain HTML pages
next to the signed files, plus the stylesheet, the images and Netlify's _headers. Pages carry no scripts.

Every piece of text in a profile was written on someone else's PC, by an agent or by the app itself, so
all of it is escaped, and the free text agents wrote is shown in quotes as information.

    python site/build.py --dist dist
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

from overshoulder import registry, sign
from overshoulder.osp import OspError, Profile, dec, loads

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
SITE = "https://overshoulder.yepgent.com"
SOURCE = "https://github.com/drknowhow/overshoulder"
REGISTRY = f"https://github.com/{registry.REPO}"
YEP = "https://github.com/yepgent"
NAME = "Overshoulder"
TAGLINE = "Your agent works in its window. Your desk stays yours."
# Copied as they are. site.css is copied under a name with its hash, so it can be cached for a year.
ASSETS = ("mark.svg", "icon-32.png", "icon-256.png", "wordmark.png", "social-preview.png", "tutorial.mp4",
          "tutorial-poster.jpg")
TUTORIAL_STEPS = ("Clear", "Four", "Eight", "Decimal separator", "Five", "Zero", "Multiply by", "One", "Five",
                  "Percent", "Equals")

# Words for what a profile records. A value missing here is shown as it is in the file (fail-safe):
# the page still reads, just less plainly, so a new Overshoulder method never breaks the build.
TYPE_WORDS = {"button": "button", "listitem": "list item", "tabitem": "tab", "menuitem": "menu item",
              "menu": "menu", "document": "document", "edit": "text box", "checkbox": "check box",
              "combobox": "drop-down list", "radiobutton": "option button", "hyperlink": "link", "text": "text",
              "tree": "tree", "treeitem": "tree item", "list": "list", "tab": "tab strip", "window": "window",
              "pane": "pane", "image": "image", "slider": "slider", "spinner": "spinner", "dataitem": "cell",
              "splitbutton": "split button", "toolbar": "toolbar", "group": "group", "custom": "custom control",
              "dialog": "dialog", "focus": "focused control"}
METHOD_WORDS = {"uia_invoke": "UI Automation's invoke", "uia_select": "UI Automation's select",
                "uia_toggle": "UI Automation's toggle", "uia_value": "UI Automation's set value",
                "uia_focus": "UI Automation's focus", "button_message": "a button message to the window",
                "set_text_message": "a set-text message to the window", "replace_selection": "replacing the selection",
                "posted_keys": "keystrokes posted to the window", "posted_chars": "characters posted to the window",
                "posted_click": "a click posted to the window", "posted_drag": "a drag posted to the window",
                "real_click": "the real mouse", "real_drag": "the real mouse", "real_keys": "the real keyboard",
                "real_typing": "the real keyboard", "scope_focus": "focusing the window", "any": "any method"}


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def said(text: str) -> str:
    """Free text an agent wrote: quoted and marked, never markup."""
    return f'<q class="said">{esc(text)}</q>'


def day(iso: str) -> str:
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return esc(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def size(n: int) -> str:
    return f"{n} bytes" if n < 1024 else f"{n / 1024:.1f} KB"


def times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def type_word(t: str) -> str:
    return TYPE_WORDS.get(t.lower(), t)


def app_url(app: str) -> str:
    return f"/apps/{quote(app)}/"


def profile_url(entry: dict) -> str:
    return f"/apps/{quote(entry['app'])}/{quote(entry['by'])}/"


def file_name(entry: dict) -> str:
    return f"{slug(entry['name']) or 'profile'}.osp"


# What a profile holds, in words. Each function takes the items of one kind and returns list items.

def _hows(items) -> list[str]:
    out = []
    for x in items:
        steps = [" ".join(dec(t) for t in s) for s in x.steps]
        line = said(x.text or x.id)
        if steps:
            line += ": " + ", then ".join(f"<i>{esc(s)}</i>" for s in steps)
        used = x.num("used")
        if used:
            line += f". Agents have followed it {times(used)}."
        out.append(line)
    return out


def _ways(items) -> list[str]:
    out = []
    for x in items:
        action, _, rest = x.id.partition("@")
        where, _, method = rest.partition(".")
        ok, fail = x.num("ok"), x.num("fail")
        on = "the focused control" if where == "focus" else f"a {esc(type_word(where))}"
        line = (f"{esc(action.capitalize())} on {on}, through {esc(METHOD_WORDS.get(method, method.replace('_', ' ')))}: "
                f"worked {ok} of {ok + fail}")
        out.append(line + ("." if ok else ", so agents try another method first."))
    return out


def _controls(items) -> list[str]:
    out, hidden = [], []
    for x in items:
        kind = type_word(x.args[1]) if len(x.args) > 1 else "control"
        if not x.text:
            hidden.append(kind)
            continue
        extra = []
        if x.num("ask"):
            extra.append("you were asked before agents used it")
        if x.num("fail"):
            extra.append(f"worked {x.num('ok')} of {x.num('ok') + x.num('fail')}")
        out.append(f"{esc(x.text)} <span class=\"note\">({esc(kind)}{'; ' + '; '.join(extra) if extra else ''})</span>")
    if hidden:
        kinds = ", ".join(sorted(set(hidden)))
        out.append(f"{plural(len(hidden), 'control')} ({esc(kinds)}) named by the person's own content, so only "
                   "the kind is kept")
    return out


def _keys(items) -> list[str]:
    out = []
    for x in items:
        combo = "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in dec(x.id).split("+"))
        line = f"<code>{esc(combo)}</code>"
        if x.text:
            line += f" {said(x.text)}"
        if x.num("n"):
            line += f" <span class=\"note\">(used {times(x.num('n'))})</span>"
        out.append(line)
    return out


def _paints(items) -> list[str]:
    return [f"{said(x.text or x.id)} <span class=\"note\">(found by its look in the {esc(x.args[0] if x.args else 'main')} "
            f"window{', ' + times(x.num('hit')) if x.num('hit') else ''})</span>" for x in items]


def _views(items) -> list[str]:
    counts: dict[str, int] = {}
    for x in items:
        t = type_word(x.args[0]) if x.args else "window"
        counts[t] = counts.get(t, 0) + 1
    return [plural(n, t) for t, n in sorted(counts.items())]


def _quirks(items) -> list[str]:
    return [said(x.text or x.id) for x in items]


def _notes(items) -> list[str]:
    out = []
    for x in items:
        url = dec(x.fields.get("url", ""))
        line = said(x.text or x.id)
        if url.startswith(("https://", "http://")):
            line += f'<br><a href="{esc(url)}" rel="nofollow ugc noopener noreferrer">{esc(url)}</a>'
        out.append(line)
    return out


SECTIONS = (("how", "How-tos", _hows), ("way", "What works", _ways), ("ctl", "Controls", _controls),
            ("key", "Shortcuts", _keys), ("paint", "Found by their look", _paints), ("view", "Windows", _views),
            ("quirk", "Quirks", _quirks), ("note", "Guide notes", _notes))


def holds(prof: Profile) -> str:
    """The profile's items as boxes, in the order a person would want them."""
    boxes = []
    known = {k for k, _, _ in SECTIONS}
    for kind, title, words in SECTIONS:
        items = [x for x in prof.items if x.kind == kind]
        if not items:
            continue
        lis = "".join(f"<li>{w}</li>" for w in words(items))
        boxes.append(f'<section class="box"><h3>{esc(title)} · {len(items)}</h3><ul>{lis}</ul></section>')
    other = [x for x in prof.items if x.kind not in known]
    if other:  # a kind this site doesn't describe yet: count it, the full file is below
        boxes.append(f'<section class="box"><h3>Other · {len(other)}</h3><p class="small">Listed in the file '
                     'below.</p></section>')
    return f'<div class="holds">{"".join(boxes)}</div>'


# Pages

def page(title: str, description: str, path: str, body: str, css: str, home: bool = False) -> str:
    full = title if home else f"{title} · {NAME} profiles"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{SITE}{esc(path)}">
<meta name="theme-color" content="#0b1220">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{esc(full)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{SITE}{esc(path)}">
<meta property="og:image" content="{SITE}/social-preview.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/mark.svg" type="image/svg+xml">
<link rel="icon" href="/icon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/icon-256.png">
<link rel="stylesheet" href="/{css}">
</head>
<body{' class="home"' if home else ''}>
<a class="skip" href="#main">Skip to the content</a>
<header class="top"><div class="wrap">
<a class="brand" href="/"><img src="/wordmark.png" alt="{NAME}" width="159" height="28"></a>
<nav aria-label="Site"><a href="/#profiles">Profiles</a><a href="/#install">Install</a><a href="/#share">Share yours</a><a href="{SOURCE}">GitHub</a></nav>
</div></header>
{body}
</body>
</html>
"""


def footer(index: dict) -> str:
    commit = index.get("commit") or ""
    built = f"Catalog built {day(index.get('built', ''))}"
    if commit:
        built += f' from <a href="{REGISTRY}/commit/{esc(commit)}">{esc(commit[:7])}</a>'
    return f"""<footer><div class="wrap">
<p>A site by Yep (<a href="{YEP}">@yepgent</a>). {NAME} is open source under the MIT licence; profiles are in the public domain under CC0.</p>
<p>{built}: <a href="/index.json">index.json</a> and its signature, <a href="/index.json.sig">index.json.sig</a>. <a href="{REGISTRY}">The registry on GitHub</a>.</p>
</div></footer>"""


def home(index: dict, apps: dict[str, list[dict]], css: str) -> str:
    if apps:
        cards = []
        for app, entries in sorted(apps.items(), key=lambda kv: kv[1][0]["name"].lower()):
            first = entries[0]
            href = profile_url(first) if len(entries) == 1 else app_url(app)
            line = (f"{plural(first['items'], 'item')} · by @{esc(first['by'])}" if len(entries) == 1
                    else f"{plural(len(entries), 'profile')}")
            cards.append(f'<li><a href="{href}"><b>{esc(first["name"])}</b><span>{line}</span></a></li>')
        listing = f'<ul class="cards">{"".join(cards)}</ul>'
    else:
        listing = ('<p class="empty">No profile has been published yet. Yours could be the first: '
                   '<a href="#share">share one</a>.</p>')
    steps = "".join(f"<li>Click {esc(s)}</li>" for s in TUTORIAL_STEPS)
    body = f"""<div class="hero"><div class="wrap">
<div class="hero-text">
<h1>{TAGLINE}</h1>
<p class="lede">{NAME} is an open-source MCP server for Windows. An AI agent takes one app window, sees its controls,
and clicks and types inside it in the background while you keep your own mouse and keyboard. It can record what it
did as a tutorial with numbered steps.</p>
<pre class="install"><code>git clone {SOURCE}</code></pre>
<p class="actions"><a class="btn" href="#profiles">Find app profiles</a><a class="btn ghost" href="{SOURCE}">Source on GitHub</a></p>
</div>
<figure class="demo">
<video src="/tutorial.mp4" poster="/tutorial-poster.jpg" width="406" height="738" autoplay muted loop playsinline controls
 aria-label="A tutorial {NAME} recorded: an agent works out a 15% tip on 48.50 in Calculator"></video>
<figcaption>A tutorial {NAME} recorded while an agent worked out a 15% tip on 48.50 in Calculator.
<details><summary>The steps</summary><ol>{steps}</ol></details></figcaption>
</figure>
</div></div>
<main id="main"><div class="wrap">
<section id="profiles" aria-labelledby="profiles-h">
<h2 id="profiles-h">Profiles on the registry</h2>
<p>A profile is what agents learned about one Windows app: its windows and controls, which methods work there, its
shortcuts and quirks, and short how-tos. {NAME} hands it to an agent when the agent takes a window of that app, so it
starts with what earlier agents learned. A profile is information: it never lets an agent do more than you allow.</p>
{listing}
<p class="small">To use one, download it and open the file. {NAME} shows everything in it and adds nothing until you
say yes.</p>
</section>
<section id="install" aria-labelledby="install-h">
<h2 id="install-h">Install</h2>
<p>{NAME} runs on Windows 10 and 11. It needs Python 3.11 or later, and ffmpeg for recording.</p>
<pre class="code"><code>git clone {SOURCE}
cd overshoulder
python -m venv .venv
.venv\\Scripts\\pip install -e .</code></pre>
<p>Then start it and connect an agent; the <a href="{SOURCE}#quick-start">quick start</a> covers both. Any agent that
speaks MCP can use it.</p>
</section>
<section id="share" aria-labelledby="share-h">
<h2 id="share-h">Share what your agents learned</h2>
<ol class="steps">
<li>Export the profile: <code>overshoulder profile export &lt;app&gt;</code>, or Export on the settings page. An export
leaves out window titles, typed text, file names and anything seen in only one session.</li>
<li>Open a pull request on <a href="{REGISTRY}">the registry</a> that adds it at
<code>apps/&lt;app id&gt;/&lt;your GitHub login&gt;.osp</code>.</li>
<li>Checks run on the pull request. Then Yep reviews it and merges it, the registry signs it, and it appears here.</li>
</ol>
<p class="small"><a href="{REGISTRY}/blob/main/CONTRIBUTING.md">What the checks refuse</a>. Profiles are in the public
domain under CC0, so anyone may use them for anything.</p>
</section>
</div></main>
{footer(index)}"""
    return page(f"{NAME}: {TAGLINE}", "Overshoulder lets AI agents see, operate and record Windows apps in the "
                "background. Shared app profiles tell agents what earlier agents learned about an app.", "/",
                body, css, home=True)


def app_page(index: dict, entries: list[dict], css: str) -> str:
    first = entries[0]
    rows = "".join(
        f'<li><a href="{profile_url(e)}"><b>by @{esc(e["by"])}</b><span>{plural(e["items"], "item")} · revision '
        f'{e["rev"]} · {day(e["at"])}</span></a></li>' for e in entries)
    body = f"""<main id="main" class="wrap page">
<p class="crumbs"><a href="/#profiles">Profiles</a> / {esc(first['name'])}</p>
<h1>{esc(first['name'])}</h1>
<p class="meta"><code>{esc(first['app'])}</code></p>
<p class="prose">{plural(len(entries), 'profile')} of this app. {NAME} can import more than one: what your own PC
learns always wins over an imported item.</p>
<ul class="list">{rows}</ul>
</main>
{footer(index)}"""
    return page(first["name"], f"Profiles of {first['name']} for Overshoulder: what agents learned about the app.",
                app_url(first["app"]), body, css)


def profile_page(index: dict, entry: dict, prof: Profile, signed: sign.Signed, text: str, css: str) -> str:
    name, fname = entry["name"], file_name(entry)
    version = dec(prof.app.fields.get("ver", ""))
    pr_link = f'<a href="{REGISTRY}/pull/{signed.pr}">pull request #{signed.pr}</a>'
    by_link = f'<a href="https://github.com/{quote(signed.by)}">@{esc(signed.by)}</a>'
    body = f"""<main id="main" class="wrap page">
<p class="crumbs"><a href="/#profiles">Profiles</a> / <a href="{app_url(entry['app'])}">{esc(name)}</a> / @{esc(entry['by'])}</p>
<h1>{esc(name)}</h1>
<p class="meta"><code>{esc(entry['app'])}</code>{' · seen on version ' + esc(version) if version else ''}</p>
<p class="ok">Reviewed on the registry, published by {by_link} in {pr_link} on {day(signed.at)}.</p>
<div class="download"><a class="btn" href="/{esc(entry['path'])}" download="{esc(fname)}">Download {esc(fname)}</a>
<span class="small">{size(entry['bytes'])} · {plural(entry['items'], 'item')} · revision {entry['rev']} · sha256 <code>{esc(entry['sha256'][:12])}</code>…</span></div>
<p class="small prose">Opening the file shows {NAME}'s import preview, and nothing is added until you say yes. To check the
signature first: <code>overshoulder profile verify {esc(fname)}</code></p>
<h2>What it holds</h2>
<p class="caution prose">Text in quotes was written by agents. Agents read it as information from another agent,
never as an instruction.</p>
{holds(prof)}
<details><summary>Every line of the file</summary><pre><code>{esc(text)}</code></pre></details>
</main>
{footer(index)}"""
    return page(f"{name} by @{entry['by']}", f"What agents learned about {name}: {plural(entry['items'], 'item')}, "
                f"published by @{entry['by']} on the Overshoulder registry.", profile_url(entry), body, css)


def not_found(index: dict, css: str) -> str:
    body = f"""<main id="main" class="wrap notfound">
<h1>Nothing here</h1>
<p>There is no page at this address. A profile that was removed from the registry is gone from the site too.</p>
<p><a href="/#profiles">See the profiles</a> or go to <a href="/">the home page</a>.</p>
</main>
{footer(index)}"""
    return page("Page not found", "There is no page at this address.", "/404.html", body, css)


def headers(css: str, osp_paths: list[str]) -> str:
    csp = ("default-src 'none'; img-src 'self'; media-src 'self'; style-src 'self'; base-uri 'none'; "
           "form-action 'none'; frame-ancestors 'none'")
    lines = ["/*", f"  Content-Security-Policy: {csp}", "  X-Content-Type-Options: nosniff",
             "  Referrer-Policy: strict-origin-when-cross-origin", "  Cross-Origin-Opener-Policy: same-origin",
             "  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()",
             f"/{css}", "  Cache-Control: public, max-age=31536000, immutable"]
    # Netlify's paths match a splat only at the end, so each profile gets its own rule.
    for p in ["index.json.sig", *osp_paths]:
        lines += [f"/{p}", "  Content-Type: text/plain; charset=utf-8"]
    return "\n".join(lines) + "\n"


def sitemap(urls: list[str]) -> str:
    rows = "".join(f"<url><loc>{SITE}{esc(u)}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>\n')


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build(dist: Path, keys: dict[str, str] | None = None) -> dict:
    """Write the site into dist/, which already holds index.json, its signature and the signed profiles."""
    index = registry.read_index((dist / "index.json").read_bytes(), (dist / "index.json.sig").read_text("utf-8"),
                                keys)
    apps: dict[str, list[dict]] = {}
    loaded = []
    for entry in index["profiles"]:
        data = (dist / entry["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise OspError(f"{entry['path']} does not match the catalog's hash")
        prof = loads(data.decode("utf-8"))
        signed = sign.verify(prof, keys)
        if signed is None:
            raise OspError(f"{entry['path']} is not signed")
        loaded.append((entry, prof, signed, data.decode("utf-8")))
        apps.setdefault(entry["app"], []).append(entry)

    css_text = (STATIC / "site.css").read_bytes()
    css = f"site.{hashlib.sha256(css_text).hexdigest()[:10]}.css"
    for old in dist.glob("site.*.css"):
        old.unlink()
    (dist / css).write_bytes(css_text)
    for name in ASSETS:
        shutil.copyfile(STATIC / name, dist / name)

    urls = ["/"]
    _write(dist / "index.html", home(index, apps, css))
    for app, entries in apps.items():
        _write(dist / "apps" / app / "index.html", app_page(index, entries, css))
        urls.append(app_url(app))
    for entry, prof, signed, text in loaded:
        _write(dist / "apps" / entry["app"] / entry["by"] / "index.html",
               profile_page(index, entry, prof, signed, text, css))
        urls.append(profile_url(entry))
    _write(dist / "404.html", not_found(index, css))
    _write(dist / "_headers", headers(css, [e["path"] for e, *_ in loaded]))
    _write(dist / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    _write(dist / "sitemap.xml", sitemap(urls))
    return {"pages": len(urls) + 1, "profiles": len(loaded), "css": css}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", default="dist", help="the folder registry build wrote")
    a = ap.parse_args(argv)
    try:
        out = build(Path(a.dist))
    except (OspError, OSError) as e:
        print(f"site build failed: {e}", file=sys.stderr)
        return 1
    print(f"site: {out['pages']} pages, {out['profiles']} profiles, {out['css']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
