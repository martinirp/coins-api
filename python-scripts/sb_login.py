import os
import sys
import json
import time
import shutil
import pyotp
import undetected_chromedriver as uc

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_env_path(env_path):
    if os.path.isabs(env_path):
        return env_path
    return os.path.join(SCRIPT_DIR, env_path)


def load_env(env_path):
    env_vars = {}
    resolved_path = resolve_env_path(env_path)
    if os.path.exists(resolved_path):
        with open(resolved_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key_val = line.split("=", 1)
                    if len(key_val) == 2:
                        key = key_val[0].strip()
                        val = key_val[1].strip()
                        if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                            val = val[1:-1]
                        env_vars[key] = val
    return env_vars


def find_chromium_bin():
    for name in ("chromium", "chromium-browser", "chrome", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    if os.path.exists("/usr/bin/chromium"):
        return "/usr/bin/chromium"
    return None


def find_chromedriver_bin():
    for name in ("chromedriver",):
        p = shutil.which(name)
        if p:
            return p
    for cand in ("/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"):
        if os.path.exists(cand):
            return cand
    return None


def make_driver():
    chromium_bin = find_chromium_bin()
    chromedriver_bin = find_chromedriver_bin()

    if not chromium_bin:
        raise RuntimeError("Binario chromium nao encontrado. Rode: apt install -y chromium chromium-driver")
    if not chromedriver_bin:
        raise RuntimeError("chromedriver nao encontrado. Rode: apt install -y chromium chromium-driver")

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
        "--lang=en-US,en",
        "--disable-blink-features=AutomationControlled",
    ):
        try:
            options.add_argument(arg)
        except Exception:
            pass
    options.add_argument("--headless=new")

    kwargs = dict(
        options=options,
        driver_executable_path=chromedriver_bin,
        use_subprocess=True,
        version_main=None,
    )

    return uc.Chrome(**kwargs)


def stealth(driver):
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                window.chrome = window.chrome || { runtime: {} };
            """},
        )
    except Exception:
        pass


def wait_for(driver, css, timeout=45, state="present"):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    if state == "visible":
        cond = EC.visibility_of_element_located((By.CSS_SELECTOR, css))
    else:
        cond = EC.presence_of_element_located((By.CSS_SELECTOR, css))
    return WebDriverWait(driver, timeout).until(cond)


def main():
    env = load_env(".env")
    email = env.get("TIBIA_EMAIL")
    password = env.get("TIBIA_PASSWORD")
    totp_secret = env.get("TIBIA_TOTP_KEY")

    if not email or not password or not totp_secret:
        print("[-] ERRO: Credenciais ou chave TOTP ausentes no arquivo .env.")
        sys.exit(1)

    login_url = "https://www.tibia.com/account/?subtopic=accountmanagement"

    print(f"[*] Iniciando login headless (undetected-chromedriver) em {login_url}...", flush=True)

    driver = make_driver()
    try:
        stealth(driver)

        print("[*] Abrindo pagina de login...", flush=True)
        driver.get(login_url)

        print("[*] Aguardando Cloudflare + formulario...", flush=True)
        try:
            wait_for(driver, 'input[name="loginemail"]', timeout=60, state="present")
            print("[+] Pagina de login carregada.", flush=True)
        except Exception:
            try:
                html = driver.page_source[:500]
            except Exception:
                html = ""
            print("[-] Timeout waiting login form. Inicio HTML:", html, flush=True)
            raise RuntimeError("Formulario de login nao apareceu (possivel bloqueio Cloudflare)")

        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        email_el = driver.find_element(By.CSS_SELECTOR, 'input[name="loginemail"]')
        pwd_el = driver.find_element(By.CSS_SELECTOR, 'input[name="loginpassword"]')
        email_el.clear()
        email_el.send_keys(email)
        pwd_el.clear()
        pwd_el.send_keys(password)
        pwd_el.send_keys(Keys.Return)

        print("[*] Aguardando TOTP ou Logout...", flush=True)
        is_totp = False
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                src = driver.page_source
            except Exception:
                src = ""
            if 'name="totp"' in src or "totp" in src.lower():
                is_totp = True
                break
            if "Logout" in src:
                break
            time.sleep(0.2)

        if is_totp:
            print("[*] 2FA (TOTP) solicitado! Gerando token...", flush=True)
            code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
            try:
                wait_for(driver, 'input[name="totp"]', timeout=15, state="present")
            except Exception:
                pass
            totp_el = driver.find_element(By.CSS_SELECTOR, 'input[name="totp"]')
            totp_el.clear()
            totp_el.send_keys(code)
            totp_el.send_keys(Keys.Return)

        print("[*] Aguardando conclusao do login (Logout)...", flush=True)
        ok = False
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                if "Logout" in driver.page_source:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(0.2)

        if not ok:
            try:
                tail = driver.page_source[-300:]
            except Exception:
                tail = ""
            print("[-] Login falhou. Final HTML:", tail, flush=True)
            sys.exit(1)

        print("[+] LOGIN BEM SUCEDIDO!", flush=True)

        history_url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"
        print(f"[*] Navegando ate {history_url}...", flush=True)
        driver.get(history_url)
        try:
            wait_for(driver, "table", timeout=10, state="present")
        except Exception:
            pass

        cookies = driver.get_cookies()
        cookie_parts = [f"{c['name']}={c['value']}" for c in cookies if "tibia.com" in c.get("domain", "")]
        cookie_string = "; ".join(cookie_parts)

        if not cookie_string:
            raise RuntimeError("Nenhum cookie do dominio tibia.com capturado")

        cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
        with open(cookie_file_path, "w", encoding="utf-8") as f:
            f.write(cookie_string)
        print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!", flush=True)

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()