import os
import sys
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


def ensure_display():
    """Se nao houver display, relanca o proprio script sob Xvfb (melhor fingerprint pro Turnstile)."""
    if os.environ.get("DISPLAY"):
        return
    xvfb = shutil.which("xvfb-run")
    if xvfb:
        print("[*] Sem DISPLAY. Reiniciando sob Xvfb (display virtual)...", flush=True)
        os.execv(xvfb, [xvfb, "-a", sys.executable] + sys.argv)
    else:
        print("[*] Sem DISPLAY e sem xvfb-run. Seguindo em headless puro...", flush=True)


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
    print(f"[*] DISPLAY={os.environ.get('DISPLAY')!r}", flush=True)

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

    has_display = bool(os.environ.get("DISPLAY"))
    if not has_display:
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


def snapshot(driver, name):
    """Salva screenshot + dump HTML + loga URL/title para depuracao."""
    try:
        title = (driver.title or "").strip()
    except Exception:
        title = "<erro>"
    try:
        url = driver.current_url
    except Exception:
        url = "<erro>"
    print(f"[snap] {name}: url={url!r} title={title!r}", flush=True)
    try:
        path = os.path.join(SCRIPT_DIR, name + ".png")
        driver.save_screenshot(path)
        print(f"[snap] {name}.png salvo em {path}", flush=True)
    except Exception as e:
        print(f"[snap] falha ao salvar {name}.png: {e}", flush=True)
    try:
        html = driver.page_source
        html_path = os.path.join(SCRIPT_DIR, name + ".html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[snap] {name}.html salvo em {html_path} ({len(html)} chars)", flush=True)
    except Exception as e:
        print(f"[snap] falha ao salvar {name}.html: {e}", flush=True)


def try_click_turnstile(driver, timeout=25):
    """Procura o iframe do Turnstile e clica no checkbox, se presente. Retorna True se o formulario aparecer."""
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    clicked = False
    while time.time() < deadline:
        try:
            if driver.find_elements(By.CSS_SELECTOR, 'input[name="loginemail"]'):
                return True

            for frame in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = frame.get_attribute("src") or ""
                except Exception:
                    src = ""
                if "challenges.cloudflare.com" in src or "turnstile" in src:
                    try:
                        driver.switch_to.frame(frame)
                        selectors = [
                            'input[type="checkbox"]',
                            "#challenge-stage input[type='checkbox']",
                            ".ctp-checkbox-label",
                            "label[for=challenge]",
                            "#spr1",
                            "#challenge-stage",
                        ]
                        for sel in selectors:
                            els = driver.find_elements(By.CSS_SELECTOR, sel)
                            if els:
                                try:
                                    els[0].click()
                                except Exception:
                                    pass
                                clicked = True
                                break
                    except Exception:
                        pass
                    finally:
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
        except Exception:
            pass

        if clicked and driver.find_elements(By.CSS_SELECTOR, 'input[name="loginemail"]'):
            return True

        time.sleep(1)

    return bool(driver.find_elements(By.CSS_SELECTOR, 'input[name="loginemail"]'))


def solve_turnstile_token(driver, timeout=20):
    """Tenta resolver o widget Turnstile (dentro do form) e retorna o token, se gerado."""
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            token_input = driver.find_elements(By.CSS_SELECTOR, 'input[name="cf-turnstile-response"]')
            if token_input and token_input[0].get_attribute("value"):
                return token_input[0].get_attribute("value")
        except Exception:
            pass

        try:
            for frame in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = frame.get_attribute("src") or ""
                except Exception:
                    src = ""
                if "challenges.cloudflare.com" in src or "turnstile" in src:
                    try:
                        driver.switch_to.frame(frame)
                        for sel in ('input[type="checkbox"]', ".ctp-checkbox-label", "#challenge-stage", "#spr1"):
                            els = driver.find_elements(By.CSS_SELECTOR, sel)
                            if els:
                                try:
                                    els[0].click()
                                except Exception:
                                    pass
                                break
                    except Exception:
                        pass
                    finally:
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            token_input = driver.find_elements(By.CSS_SELECTOR, 'input[name="cf-turnstile-response"]')
            if token_input and token_input[0].get_attribute("value"):
                return token_input[0].get_attribute("value")
        except Exception:
            pass

        time.sleep(1)
    return None


def dump_error_hints(driver):
    """Procura elementos de texto com palavras de erro/captcha na pagina."""
    from selenium.webdriver.common.by import By

    for el in driver.find_elements(
        By.XPATH, "//*[self::div or self::span or self::p or self::td or self::h1 or self::h2 or self::label]"
    ):
        try:
            txt = (el.text or "").strip()
        except Exception:
            txt = ""
        low = txt.lower()
        if txt and any(k in low for k in ("captcha", "invalid", "error", "try again", "incorrect", "wrong", "blocked", "turnstile")):
            try:
                cls = el.get_attribute("class")
            except Exception:
                cls = None
            print(f"[hint] <{el.tag_name} class={cls!r}> {txt[:200]!r}", flush=True)


def main():
    ensure_display()

    env = load_env(".env")
    email = env.get("TIBIA_EMAIL")
    password = env.get("TIBIA_PASSWORD")
    totp_secret = env.get("TIBIA_TOTP_KEY")

    if not email or not password or not totp_secret:
        print("[-] ERRO: Credenciais ou chave TOTP ausentes no arquivo .env.")
        sys.exit(1)

    login_url = "https://www.tibia.com/account/?subtopic=accountmanagement"

    print(f"[*] Iniciando login em {login_url}...", flush=True)

    driver = make_driver()
    try:
        try:
            stealth(driver)
        except Exception as e:
            print(f"[*] stealth patch aviso: {e}", flush=True)

        print("[*] Abrindo pagina de login...", flush=True)
        driver.get(login_url)

        print("[*] Aguardando Cloudflare/Turnstile + formulario...", flush=True)
        from selenium.webdriver.common.by import By

        form_ok = False
        for attempt in range(1, 5):
            if driver.find_elements(By.CSS_SELECTOR, 'input[name="loginemail"]'):
                form_ok = True
                break
            print(f"[*] Tentativa {attempt}: procurando/clicando Turnstile...", flush=True)
            try_click_turnstile(driver, timeout=30)
            if driver.find_elements(By.CSS_SELECTOR, 'input[name="loginemail"]'):
                form_ok = True
                break
            if attempt < 4:
                print("[*] Relendo a pagina...", flush=True)
                driver.get(login_url)
                time.sleep(3)

        if not form_ok:
            try:
                html = driver.page_source[:500]
            except Exception:
                html = ""
            print("[-] Formulario de login nao apareceu. Inicio HTML:", html, flush=True)
            raise RuntimeError("Formulario de login nao apareceu (possivel bloqueio Cloudflare)")

        print("[+] Pagina de login carregada.", flush=True)
        snapshot(driver, "sb_login_page")

        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        email_el = driver.find_element(By.CSS_SELECTOR, 'input[name="loginemail"]')
        pwd_el = driver.find_element(By.CSS_SELECTOR, 'input[name="loginpassword"]')
        email_el.clear()
        email_el.send_keys(email)
        pwd_el.clear()
        pwd_el.send_keys(password)

        masked = f"{password[:2]}***{password[-2:]}" if len(password) > 4 else "***"
        print(f"[*] Credencial enviada: email={email!r} senha_len={len(password)} senha={masked!r}", flush=True)

        has_cf = any(
            "challenges.cloudflare.com" in (f.get_attribute("src") or "")
            or "turnstile" in (f.get_attribute("src") or "")
            for f in driver.find_elements(By.TAG_NAME, "iframe")
        )
        if has_cf:
            token = solve_turnstile_token(driver, timeout=20)
            print(f"[*] Turnstile no form: {'PRESENTE' if token else 'FALHOU'}", flush=True)
        else:
            print("[*] Sem widget Turnstile no form (scan rapido).", flush=True)
        snapshot(driver, "sb_before_submit")
        pwd_el.send_keys(Keys.RETURN)
        snapshot(driver, "sb_after_submit")

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
            try_click_turnstile(driver, timeout=1)
            time.sleep(0.2)
        snapshot(driver, "sb_after_wait_totp")

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
            totp_el.send_keys(Keys.RETURN)
            snapshot(driver, "sb_after_totp_submit")

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
            try_click_turnstile(driver, timeout=1)
            time.sleep(0.2)
        snapshot(driver, "sb_final")

        if not ok:
            dump_error_hints(driver)
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