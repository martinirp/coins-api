import sys
from scrapling.fetchers import StealthyFetcher

print("[*] Abrindo tibia.com headless via StealthyFetcher...", flush=True)
try:
    page = StealthyFetcher.fetch(
        "https://www.tibia.com",
        headless=True,
        solve_cloudflare=True,
        timeout=60000,
        google_search=False,
        extra_flags=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )
    title = page.css("title::text").get()
    print(f"[+] HTTP {page.status} | title = {title!r}", flush=True)
    if title and "tibia" in title.lower():
        print("[+] SPIKE OK: Chromium abriu e o CF foi bypassado. Pode refatorar.", flush=True)
    else:
        print("[-] SPIKE FALHOU: a pagina nao parece o tibia. Inicio do HTML:", flush=True)
        print(page.body[:500], flush=True)
        sys.exit(1)
except Exception as e:
    print(f"[-] SPIKE ERRO: {e}", flush=True)
    sys.exit(1)