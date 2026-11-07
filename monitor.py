#!/usr/bin/env python3
"""Watch the UoC Faculty of Science SIS result sheet and push a phone
notification (via ntfy.sh) whenever a course's status or grade changes.

Read-only: it logs in and views the result sheet, nothing else.

Environment variables:
  SIS_USER, SIS_PASS   SIS login (store as secrets, never in code)
  NTFY_TOPIC           your private ntfy topic name (treat like a password)
  STATE_FILE           where the last snapshot is kept (default: state.json)
  NTFY_SERVER          optional, default https://ntfy.sh
"""
import html, http.cookiejar, json, os, re, sys, urllib.parse, urllib.request

BASE = "https://sis.cmb.ac.lk/sci"
RESULT_URL = BASE + "/results/result_sheet"
LOGIN_URL = BASE + "/ajax.php?req=login"
UA = "Mozilla/5.0 (results-watcher; personal use)"


def fetch_result_sheet():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", UA)]
    op.open(RESULT_URL, timeout=60).read()  # get session cookie
    data = urllib.parse.urlencode({
        "uname": os.environ["SIS_USER"], "pw": os.environ["SIS_PASS"],
        "log": "1", "requested_url": "/sci/results/result_sheet",
    }).encode()
    op.open(LOGIN_URL, data, timeout=60).read()
    page = op.open(RESULT_URL, timeout=60).read().decode("utf-8", "replace")
    if "<title>SignIn" in page:
        raise RuntimeError("Login failed (still on the SignIn page)")
    return page


def parse(page):
    rows = {}
    for tr in re.findall(r"(?is)<tr>(.*?)</tr>", page):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", "", c))).strip()
                 for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)]
        if len(cells) == 11 and cells[0].isdigit():
            rid, lvl, code, title, cr, typ, yr, sem, status, grade, gpv = cells
            rows[rid] = {"code": code, "title": title, "type": typ, "year": yr,
                         "sem": sem, "status": status, "grade": grade}
    if not rows:
        raise RuntimeError("No result rows found; page layout may have changed")
    return rows


def notify(title, body, priority="high"):
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(
        f"{server}/{os.environ['NTFY_TOPIC']}", data=body.encode(),
        headers={"Title": title, "Priority": priority, "Tags": "mortar_board",
                 "Click": RESULT_URL})
    urllib.request.urlopen(req, timeout=30).read()


def main():
    state_file = os.environ.get("STATE_FILE", "state.json")
    new = parse(fetch_result_sheet())
    old = None
    if os.path.exists(state_file):
        with open(state_file) as f:
            old = json.load(f)

    if old is None:
        pending = sum(1 for r in new.values() if r["grade"] in ("--", ""))
        notify("Results watcher is running",
               f"Tracking {len(new)} courses ({pending} still without a grade). "
               "You'll get a message here when anything changes.", "default")
    else:
        changes = []
        for rid, r in new.items():
            o = old.get(rid)
            if o is None:
                changes.append(f"{r['code']} {r['title']}: new entry, {r['status']}"
                               + (f" ({r['grade']})" if r['grade'] not in ('--', '') else ""))
            elif (o["status"], o["grade"]) != (r["status"], r["grade"]):
                line = f"{r['code']} {r['title']}: {r['status']}"
                if r["grade"] not in ("--", ""):
                    line += f", grade {r['grade']}"
                changes.append(line)
        if changes:
            notify(f"SIS results updated ({len(changes)})", "\n".join(changes))
        print(f"{len(changes)} change(s)")

    with open(state_file, "w") as f:
        json.dump(new, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
