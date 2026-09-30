"""FOAMZ minter — uses Getgems' official Minting API (https://github.com/getgems-io/nft-contracts/blob/main/docs/minting-api-en.md).

Needs (environment variables):
  GETGEMS_API_KEY     the key the Getgems bot sends you after you create the collection with "API" ticked
  COLLECTION          your collection address (EQ...)
  OWNER               the wallet that receives the NFTs (your FOAMZ wallet, UQ...)
  ASSETS_BASE         public base URL of the files, e.g. https://<you>.github.io/foamz-drop1
  NETWORK             testnet | mainnet            (default testnet)

Usage:
  python mint.py --batch 1                 # mint Drop 1 batch 1 (100 NFTs)
  python mint.py --ids 1,25,33             # mint specific pieces (e.g. the launch Mythics)
  python mint.py --batch 1 --limit 5       # first 5 only (testnet practice)
  python mint.py --batch 1 --dry-run       # print what would be sent, send nothing
Safe to re-run: each FOAMZ uses a fixed requestId, so Getgems ignores repeats; progress is saved in minted.json.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

API = {"testnet": "https://api.testnet.getgems.io/public-api", "mainnet": "https://api.getgems.io/public-api"}


def call(method, url, key, body=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    for k in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "accept": "application/json", "Content-Type": "application/json", "Authorization": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            if e.code == 400:
                sys.exit(f"Getgems said 400: {txt}\n(If it says 'top up your wallet', send GRAM to the gas wallet from the Getgems bot.)")
            if e.code in (401, 403):
                sys.exit(f"Getgems rejected the API key ({e.code}). Check GETGEMS_API_KEY and COLLECTION.")
            print(f"  HTTP {e.code}, retrying ({k + 1}/{tries})…", flush=True)
        except ValueError as e:
            sys.exit(f"The API key can't be sent ({e}). Re-save the GETGEMS_API_KEY_MAINNET secret with ONLY the key text.")
        except Exception as e:
            print(f"  {e}, retrying ({k + 1}/{tries})…", flush=True)
        time.sleep(8 * (k + 1))
    sys.exit("Gave up after retries — just run the same command again, it resumes safely.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int)
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    net = os.environ.get("NETWORK", "testnet").strip().lower()
    key, coll, owner, base = (os.environ.get(k, "").strip() for k in ("GETGEMS_API_KEY", "COLLECTION", "OWNER", "ASSETS_BASE"))
    raw_lines = len([l for l in key.splitlines() if l.strip()])
    # keys never contain spaces: drop line breaks, spaces and invisible characters picked up when copying from Telegram
    key = "".join(ch for ch in key if not ch.isspace() and ch not in "\u200b\u200c\u200d\ufeff\u2060")
    # tolerate pasting part of the bot's curl example: -H 'authorization: KEY'
    import re as _re
    m = _re.search(r"(\d{10,}-(?:mainnet|testnet)-[A-Za-z0-9_\-]+)", key)
    if m:
        key = m.group(1)
    elif ":" in key and key.lower().split(":", 1)[0].endswith(("authorization", "apikey", "api_key", "key")):
        key = key.split(":", 1)[1]
    key = key.strip("'\"")
    if raw_lines > 1:
        print(f"note: the API key secret had {raw_lines} lines — cleaned it into one ({len(key)} characters).", flush=True)
    print(f"network={net}  api_key={'set' if key else 'MISSING'}  collection={coll or 'MISSING'}  owner={owner or 'MISSING'}  assets={base or 'MISSING'}", flush=True)
    if not a.dry_run and not all((key, coll, owner, base)):
        sys.exit("Missing setting(s) above. Check the names in GitHub Settings -> Secrets and variables -> Actions.")
    if not a.dry_run:
        bal = call("GET", f"{API[net]}/minting/{coll}/wallet-balance", key)
        print(f"gas wallet: {json.dumps(bal.get('response', bal))}", flush=True)
    items = json.load(open("drop1_items.json"))
    if a.ids:
        want = {int(x) for x in a.ids.split(",")}
        items = [i for i in items if i["id"] in want]
    elif a.batch is not None:
        items = [i for i in items if i["batch"] == a.batch]
    else:
        sys.exit("Choose --batch N or --ids 1,2,3")
    if a.limit:
        items = items[:a.limit]
    log = json.load(open("minted.json")) if os.path.exists("minted.json") else {}
    print(f"{net}: {len(items)} FOAMZ to mint → owner {owner or '(dry run)'}", flush=True)
    for n, it in enumerate(items, 1):
        rid = f"foamz-{net}-{it['id']}"
        if log.get(rid, {}).get("status") == "ready":
            continue
        body = {"requestId": rid, "ownerAddress": owner, "name": it["name"], "description": it["description"],
                "image": f"{base}/covers/{it['id']}.webp", "lottie": f"{base}/lottie/{it['id']}.json",
                "attributes": it["attributes"]}
        if a.dry_run:
            print(json.dumps(body, indent=1) if n == 1 else f"  would mint {it['name']}", flush=True)
            continue
        r = call("POST", f"{API[net]}/minting/{coll}", key, body)
        resp = r.get("response", {})
        log[rid] = {"id": it["id"], "status": resp.get("status"), "address": resp.get("address"), "url": resp.get("url")}
        json.dump(log, open("minted.json", "w"), indent=1)
        print(f"[{n}/{len(items)}] {it['name']} ({it['tier']}) → {resp.get('status')} {resp.get('url', '')}", flush=True)
        time.sleep(1.0)                       # stays under 400 requests / 5 min
    if a.dry_run:
        return
    print("Waiting for the blockchain…", flush=True)
    pending = [rid for rid, v in log.items() if v["status"] != "ready" and rid.startswith(f"foamz-{net}-")]
    while pending:
        time.sleep(8)
        for rid in list(pending):
            r = call("GET", f"{API[net]}/minting/{coll}/{rid}", key).get("response", {})
            if r.get("status") == "ready":
                log[rid]["status"] = "ready"; pending.remove(rid)
            time.sleep(1.0)
        json.dump(log, open("minted.json", "w"), indent=1)
        print(f"  still minting: {len(pending)}", flush=True)
    print("All minted ✅  — they're in your wallet and on Getgems.", flush=True)


if __name__ == "__main__":
    main()
