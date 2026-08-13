import os
import sys
import shutil
import undetected_chromedriver as uc


def find_chromium_bin():
    for name in ("chromium", "chromium-browser", "chrome", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    if os.path.exists("/usr/bin/chromium"):
        return "/usr/bin/chromium"
    return None


def find_chromedriver_bin():
    p = shutil.which("chromedriver")
    if p:
        return p
    for cand in ("/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"):
        if os.path.exists(cand):
            return cand
    return None


def main():
    chromium_bin = find_chromium_bin()
    chromedriver_bin = find_chromedriver_bin()

    if not chromium_bin:
        print("[-] chromium nao encontrado. Rode: apt install -y chromium chromium-driver", flush=True)
        sys.exit(1)
    if not chromedriver_bin:
        print("[-] chromedriver nao encontrado. Rode: apt install -y chromium chromium-driver", flush=True)
        sys.exit(1)

    print(f"[*] Chromium: {chromium_bin}", flush=True)
    print(f"[*] Chromedriver: {chromedriver_bin}", flush=True)

    options = uc.ChromeOptions()
    options.binary_location = chromium_bin
    for arg in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
    ):
        try:
            options.add_argument(arg)
        except Exception:
            pass
    options.add_argument("--headless=new")

    print("[*] Abrindo tibia.com headless...", flush=True)
    try:
        driver = uc.Chrome(
            options=options,
            driver_executable_path=chromedriver_bin,
            use_subprocess=True,
            version_main=None,
        )
    except Exception as e:
        print(f"[-] ERRO ao iniciar Chrome: {e}", flush=True)
        sys.exit(1)

    try:
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"},
            )
        except Exception:
            pass

        driver.get("https://www.tibia.com")
        driver.implicitly_wait(15)

        title = (driver.title or "").strip()
        url = driver.current_url
        print(f"[+] title = {title!r}", flush=True)
        print(f"[+] url   = {url}", flush=True)

        if title and "tibia" in title.lower():
            print("[+] SPIKE OK: Chromium armhf abriu e o CF foi bypassado.", flush=True)
        else:
            try:
                body = driver.page_source[:400]
            except Exception:
                body = ""
            print("[-] SPIKE FALHOU: a pagina nao parece o tibia. Inicio HTML:", flush=True)
            print(body, flush=True)
            sys.exit(1)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()