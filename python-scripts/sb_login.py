import os
import sys
import pyotp
from scrapling.fetchers import StealthyFetcher
from playwright.sync_api import Page

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


def main():
    env = load_env(".env")
    email = env.get("TIBIA_EMAIL")
    password = env.get("TIBIA_PASSWORD")
    totp_secret = env.get("TIBIA_TOTP_KEY")

    if not email or not password or not totp_secret:
        print("[-] ERRO: Credenciais ou chave TOTP ausentes no arquivo .env.")
        sys.exit(1)

    login_url = "https://www.tibia.com/account/?subtopic=accountmanagement"
    captured = {}

    def do_login(page: Page):
        print("[*] Aguardando formulario de login (pos-Cloudflare)...", flush=True)
        page.wait_for_selector('input[name="loginemail"]', timeout=45000, state="attached")

        print("[*] Preenchendo e-mail e senha...", flush=True)
        page.fill('input[name="loginemail"]', email)
        page.fill('input[name="loginpassword"]', password)
        page.press('input[name="loginpassword"]', "Enter")

        print("[*] Aguardando TOTP ou conclusao do login...", flush=True)
        is_totp = False
        for _ in range(150):
            try:
                html = page.content()
            except Exception:
                html = ""
            if 'name="totp"' in html or "totp" in html.lower():
                is_totp = True
                break
            if "Logout" in html:
                break
            page.wait_for_timeout(100)

        if is_totp:
            print("[*] 2FA (TOTP) solicitado! Gerando token...", flush=True)
            code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
            page.wait_for_selector('input[name="totp"]', timeout=10000, state="attached")
            page.fill('input[name="totp"]', code)
            page.press('input[name="totp"]', "Enter")

        print("[*] Aguardando Logout (login concluido)...", flush=True)
        for _ in range(200):
            try:
                html = page.content()
            except Exception:
                html = ""
            if "Logout" in html:
                break
            page.wait_for_timeout(100)

        try:
            html_final = page.content()
        except Exception:
            html_final = ""
        if "Logout" not in html_final:
            raise RuntimeError("Login falhou: 'Logout' nao apareceu na pagina apos submeter credenciais/TOTP")

        print("[+] LOGIN BEM SUCEDIDO! Coletando cookies do contexto do navegador...", flush=True)
        all_cookies = page.context.cookies()
        cookie_parts = [
            f"{c['name']}={c['value']}"
            for c in all_cookies
            if "tibia.com" in c.get("domain", "")
        ]
        cookie_string = "; ".join(cookie_parts)
        if not cookie_string:
            raise RuntimeError("Nenhum cookie do dominio tibia.com foi capturado")
        captured["cookies"] = cookie_string

    print(f"[*] Iniciando login Scrapling (headless) em {login_url}...", flush=True)
    try:
        StealthyFetcher.fetch(
            login_url,
            headless=True,
            solve_cloudflare=True,
            timeout=120000,
            google_search=False,
            network_idle=True,
            retries=1,
            extra_flags=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            page_action=do_login,
        )
    except Exception as e:
        print(f"[-] Erro durante o StealthyFetcher.fetch: {e}", flush=True)
        sys.exit(1)

    cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
    with open(cookie_file_path, "w", encoding="utf-8") as f:
        f.write(captured["cookies"])
    print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!", flush=True)


if __name__ == "__main__":
    main()