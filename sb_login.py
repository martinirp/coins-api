import os
import sys
import json
import time
import shutil
import platform
import subprocess
import pyotp
from seleniumbase import SB

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_env_path(env_path):
    if os.path.isabs(env_path):
        return env_path
    return os.path.join(SCRIPT_DIR, env_path)

def load_env(env_path):
    env_vars = {}
    resolved_path = resolve_env_path(env_path)
    if os.path.exists(resolved_path):
        with open(resolved_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key_val = line.split('=', 1)
                    if len(key_val) == 2:
                        key = key_val[0].strip()
                        val = key_val[1].strip()
                        if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                            val = val[1:-1]
                        env_vars[key] = val
    return env_vars

# --- Credenciais ---
env = load_env('.env')
email      = env.get('TIBIA_EMAIL')
password   = env.get('TIBIA_PASSWORD')
totp_secret = env.get('TIBIA_TOTP_KEY')

if not email or not password or not totp_secret:
    print("[-] ERRO: Credenciais ou chave TOTP ausentes no arquivo .env.")
    sys.exit(1)

url = "https://www.tibia.com/account/?subtopic=accountmanagement"

is_windows = os.name == 'nt'

print(f"[*] Iniciando SeleniumBase para {url}...")

try:
    if is_windows:
        sb_context = SB(
            uc=True,
            headless=False,
            browser="chrome"
        )
    else:
        # Termux ADB Mode
        print("[*] Ambiente Termux detectado. Tentando conectar ao Chrome do Android via ADB (porta 9222)...")
        sb_context = SB(
            debugger_address="127.0.0.1:9222"
        )
        
    with sb_context as sb:
        print("[*] Acessando a pagina do Tibia...")
        if is_windows:
            sb.uc_open_with_reconnect(url, reconnect_time=10)
        else:
            sb.open(url) # Normal open for Android Chrome

        print("[*] Verificando se o Cloudflare Turnstile apareceu...")
        try:
            from turnstile_solver import solve as turnstile_solve
        except ImportError:
            turnstile_solve = None

        if turnstile_solve:
            print("[*] Usando turnstile_solver...")
            try:
                success = turnstile_solve(
                    sb.driver,
                    detect_timeout=5,
                    solve_timeout=30,
                    interval=1,
                    verify=True,
                    click_method="cdp",
                    theme="auto",
                    enable_logging=True
                )
                print(f"[*] Resultado do turnstile_solver: {success}")
            except Exception as e:
                print(f"[-] Erro no turnstile_solver: {e}")
        else:
            print("[-] turnstile_solver não instalado. Tentando método nativo...")
            try:
                if hasattr(sb, 'uc_gui_handle_captcha'):
                    sb.uc_gui_handle_captcha()
                else:
                    sb.uc_gui_click_captcha()
                print("[+] Captcha tratado (método nativo)...")
            except Exception as e:
                print(f"[*] Nota do Captcha nativo: {e}")
            
        sb.sleep(2)

        # Aguarda o Cloudflare auto-verificar (pode levar ate 10s)
        print("[*] Aguardando Cloudflare auto-verificar...")
        for _ in range(20):
            if 'loginemail' in sb.get_page_source():
                break
            sb.sleep(0.5)

        print("[*] Aguardando o carregamento dos campos de login (com tentativas de reload)...")
        login_loaded = False
        for attempt in range(3):
            try:
                sb.wait_for_element('input[name="loginemail"]', timeout=15)
                print("[+] Pagina de login carregada com sucesso!")
                login_loaded = True
                break
            except Exception:
                print(f"[*] Tentativa {attempt + 1} falhou. Cloudflare pode estar travado. Atualizando pagina...")
                sb.save_screenshot(f"sb_cf_retry_{attempt}.png")
                sb.refresh()
                sb.sleep(5)
                if turnstile_solve:
                    try:
                        turnstile_solve(sb.driver, detect_timeout=2, solve_timeout=15, verify=True, click_method="cdp", enable_logging=True)
                    except Exception:
                        pass
                else:
                    try:
                        if hasattr(sb, 'uc_gui_handle_captcha'):
                            sb.uc_gui_handle_captcha()
                        else:
                            sb.uc_gui_click_captcha()
                    except Exception:
                        pass
                sb.sleep(3)
                
        if not login_loaded:
            sb.save_screenshot("sb_error_login_page.png")
            print("[-] Timeout: Nao foi possivel carregar a tela de login. Verifique as prints sb_cf_retry_X.png")
            raise Exception("Element {input[name='loginemail']} was not present after retries!")

        print("[*] Preenchendo e-mail e senha...")
        sb.type('input[name="loginemail"]', email)
        sb.type('input[name="loginpassword"]', password + '\n')

        # Aguarda o campo de TOTP ou a conclusão do login
        is_totp_requested = False
        for _ in range(30):
            page_source = sb.get_page_source()
            if 'name="totp"' in page_source or "totp" in page_source:
                is_totp_requested = True
                break
            if "Logout" in page_source:
                break
            sb.sleep(0.1)

        if is_totp_requested:
            print("[*] 2FA (TOTP) solicitado! Gerando token...")
            clean_secret = totp_secret.replace(" ", "").upper()
            totp = pyotp.TOTP(clean_secret)
            totp_code = totp.now()
            print(f"[*] Token gerado: {totp_code}. Preenchendo...")
            sb.type('input[name="totp"]', totp_code + '\n')

            for _ in range(30):
                if "Logout" in sb.get_page_source():
                    break
                sb.sleep(0.1)

        page_source = sb.get_page_source()

        if "Logout" in page_source:
            print("[+] LOGIN BEM SUCEDIDO!")

            history_url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"
            print(f"[*] Navegando ate o historico de coins: {history_url}...")
            sb.open(history_url)

            try:
                sb.wait_for_element('table', timeout=5)
            except Exception:
                pass

            cookies = sb.get_cookies()
            cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
            cookie_string = "; ".join(cookie_parts)

            cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookie_string)

            print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
        else:
            sb.save_screenshot("sb_error_final.png")
            print("[-] Falha no login. Verifique sb_error_final.png para entender o que aconteceu.")
            sys.exit(1)

except Exception as e:
    print(f"[-] Error: {e}")
