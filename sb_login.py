import os
import sys
import json
import time
import shutil
import platform
import subprocess
import pyotp
import requests

# Import para modo Windows
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
history_url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"

is_windows = os.name == 'nt'

print(f"[*] Iniciando automacao para {url}...")

try:
    if is_windows:
        # MODO WINDOWS (SeleniumBase UC Mode)
        print("[*] Ambiente Windows detectado. Usando SeleniumBase UC Mode...")
        with SB(uc=True, headless=False, browser="chrome") as sb:
            sb.uc_open_with_reconnect(url, reconnect_time=10)
            
            print("[*] Verificando se o Cloudflare Turnstile apareceu...")
            try:
                from turnstile_solver import solve as turnstile_solve
            except ImportError:
                turnstile_solve = None

            if turnstile_solve:
                print("[*] Usando turnstile_solver...")
                try:
                    success = turnstile_solve(sb.driver, detect_timeout=5, solve_timeout=30, interval=1, verify=True, click_method="cdp", theme="auto", enable_logging=True)
                except Exception:
                    pass
            else:
                try:
                    if hasattr(sb, 'uc_gui_handle_captcha'): sb.uc_gui_handle_captcha()
                    else: sb.uc_gui_click_captcha()
                except Exception:
                    pass
                
            sb.sleep(2)

            print("[*] Aguardando Cloudflare auto-verificar...")
            for _ in range(20):
                if 'loginemail' in sb.get_page_source(): break
                sb.sleep(0.5)

            sb.wait_for_element('input[name="loginemail"]', timeout=15)
            print("[+] Pagina de login carregada com sucesso!")

            print("[*] Preenchendo e-mail e senha...")
            sb.type('input[name="loginemail"]', email)
            sb.type('input[name="loginpassword"]', password + '\n')

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
                totp_code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
                sb.type('input[name="totp"]', totp_code + '\n')
                for _ in range(30):
                    if "Logout" in sb.get_page_source(): break
                    sb.sleep(0.1)

            if "Logout" in sb.get_page_source():
                print("[+] LOGIN BEM SUCEDIDO!")
                sb.open(history_url)
                cookies = sb.get_cookies()
                cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
                cookie_string = "; ".join(cookie_parts)

                cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
                with open(cookie_file_path, "w", encoding="utf-8") as f:
                    f.write(cookie_string)
                print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
            else:
                print("[-] Falha no login.")
                sys.exit(1)

    else:
        # MODO TERMUX (APK Nativo Tibia Solver)
        print("[*] Ambiente Termux detectado. Conectando ao Aplicativo Nativo (SolverApp) via porta 8080...")
        
        API_URL = "http://127.0.0.1:8080"
        
        try:
            print(f"[*] Solicitando navegacao inicial para a pagina de login...")
            res = requests.get(f"{API_URL}/navigate?url={url}", timeout=5)
            if res.status_code != 200:
                print("[-] O App Solver nao respondeu corretamente.")
                sys.exit(1)
        except Exception as e:
            print(f"[-] O App Solver nao esta rodando no seu celular! Abra o app Tibia Solver e tente de novo. Erro: {e}")
            sys.exit(1)
            
        print("[*] Aguardando o Cloudflare carregar no aplicativo nativo (espere 10 segundos)...")
        time.sleep(15)
        
        print("[*] Enviando credenciais para o App injetar na pagina...")
        js_login = f"""
        var email = document.querySelector('input[name="loginemail"]');
        var pwd = document.querySelector('input[name="loginpassword"]');
        if (email && pwd) {{
            email.value = '{email}';
            pwd.value = '{password}';
            var form = pwd.closest('form');
            if(form) form.submit();
        }}
        """
        requests.post(f"{API_URL}/inject", data={'js': js_login})
        
        print("[*] Aguardando tela de TOTP carregar...")
        time.sleep(10)
        
        print("[*] Gerando e injetando chave TOTP...")
        totp_code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
        js_totp = f"""
        var t = document.querySelector('input[name="totp"]');
        if (t) {{
            t.value = '{totp_code}';
            var form = t.closest('form');
            if(form) form.submit();
        }}
        """
        requests.post(f"{API_URL}/inject", data={'js': js_totp})
        
        print("[*] Aguardando o login ser concluido...")
        time.sleep(10)
        
        print("[*] Navegando para o Historico de Coins...")
        requests.get(f"{API_URL}/navigate?url={history_url}")
        time.sleep(8)
        
        print("[*] Solicitando a extracao dos cookies fresquinhos diretamente do App...")
        try:
            res_cookies = requests.get(f"{API_URL}/solve").json()
            cookies = res_cookies.get('cookies', '')
            
            if cookies and "tibia.com" in cookies.lower() or len(cookies) > 10:
                cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
                with open(cookie_file_path, "w", encoding="utf-8") as f:
                    f.write(cookies)
                print(f"[+] LOGIN BEM SUCEDIDO NO APLICATIVO!")
                print(f"[+] Cookies transferidos com sucesso do App nativo para o Termux: {cookie_file_path}")
            else:
                print("[-] O App nao conseguiu capturar os cookies. A pagina de login travou no celular?")
                sys.exit(1)
        except Exception as e:
            print(f"[-] Erro ao pedir os cookies para o aplicativo: {e}")
            sys.exit(1)

except Exception as e:
    print(f"[-] Error: {e}")

