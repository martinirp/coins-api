import os
import sys
import json
import time
import shutil
import platform
import subprocess
import pyotp

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
        # MODO TERMUX ADB (CDP Websocket Puro)
        print("[*] Ambiente Termux detectado. Usando WebSocket CDP puro na porta 9222...")
        try:
            import requests
            import websocket
        except ImportError:
            print("[-] Dependencias ausentes! Rode: pip install requests websocket-client")
            sys.exit(1)
            
        print("[*] Buscando a pagina ativa no Chrome do Android...")
        try:
            resp = requests.get('http://127.0.0.1:9222/json')
            pages = resp.json()
        except Exception as e:
            print(f"[-] Erro ao conectar no Chrome. A porta 9222 ta aberta? O Chrome ta aberto? Erro: {e}")
            sys.exit(1)
            
        ws_url = None
        for p in pages:
            if p.get('type') == 'page' and 'webSocketDebuggerUrl' in p:
                ws_url = p['webSocketDebuggerUrl']
                break
                
        if not ws_url:
            print("[-] Nenhuma pagina aberta encontrada no Chrome. Abra uma nova aba vazia no celular!")
            sys.exit(1)
            
        print(f"[*] Conectando via WebSocket no Chrome...")
        ws = websocket.create_connection(ws_url)
        msg_id = 0
        
        def send_cmd(method, params=None):
            global msg_id
            msg_id += 1
            msg = {"id": msg_id, "method": method, "params": params or {}}
            ws.send(json.dumps(msg))
            while True:
                resp_str = ws.recv()
                resp_json = json.loads(resp_str)
                if resp_json.get("id") == msg_id:
                    return resp_json
        
        print(f"[*] Navegando para {url}")
        send_cmd("Page.navigate", {"url": url})
        
        print("[*] Aguardando o campo de email aparecer (espere o Cloudflare passar sozinho)...")
        email_ready = False
        for _ in range(60): # Espera ate 60 segundos
            res = send_cmd("Runtime.evaluate", {
                "expression": "document.querySelector('input[name=\"loginemail\"]') !== null",
                "returnByValue": True
            })
            if res.get('result', {}).get('result', {}).get('value') == True:
                email_ready = True
                break
            time.sleep(1)
            
        if not email_ready:
            print("[-] Timeout: O campo de email nao apareceu.")
            sys.exit(1)
            
        print("[+] Pagina de login pronta! Inserindo credenciais...")
        # Usa javascript para preencher e enviar o form
        fill_js = f"""
        var email = document.querySelector('input[name="loginemail"]');
        var pwd = document.querySelector('input[name="loginpassword"]');
        if (email && pwd) {{
            email.value = '{email}';
            pwd.value = '{password}';
            var btn = document.querySelector('input[name="Submit"]');
            if(btn) btn.click();
            else {{
                var form = pwd.closest('form');
                if (form) form.submit();
            }}
        }}
        """
        send_cmd("Runtime.evaluate", {"expression": fill_js})
        
        print("[*] Aguardando confirmacao ou campo TOTP...")
        is_totp_requested = False
        is_logged_in = False
        for _ in range(60):
            time.sleep(1)
            res = send_cmd("Runtime.evaluate", {
                "expression": "document.body.innerHTML.includes('name=\"totp\"') || document.body.innerHTML.includes('Logout')",
                "returnByValue": True
            })
            val = res.get('result', {}).get('result', {}).get('value')
            if val:
                res2 = send_cmd("Runtime.evaluate", {
                    "expression": "document.body.innerHTML.includes('Logout')",
                    "returnByValue": True
                })
                if res2.get('result', {}).get('result', {}).get('value') == True:
                    is_logged_in = True
                    break
                else:
                    is_totp_requested = True
                    break

        if is_totp_requested:
            print("[*] 2FA (TOTP) solicitado! Gerando token...")
            totp_code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
            print(f"[*] Token gerado: {totp_code}. Inserindo...")
            totp_js = f"""
            var t = document.querySelector('input[name="totp"]');
            if (t) {{
                t.value = '{totp_code}';
                var form = t.closest('form');
                if (form) form.submit();
            }}
            """
            send_cmd("Runtime.evaluate", {"expression": totp_js})
            
            for _ in range(30):
                time.sleep(1)
                res = send_cmd("Runtime.evaluate", {
                    "expression": "document.body.innerHTML.includes('Logout')",
                    "returnByValue": True
                })
                if res.get('result', {}).get('result', {}).get('value') == True:
                    is_logged_in = True
                    break
                    
        if is_logged_in:
            print("[+] LOGIN BEM SUCEDIDO!")
            print(f"[*] Navegando ate historico: {history_url}")
            send_cmd("Page.navigate", {"url": history_url})
            time.sleep(5) # Aguarda historico carregar
            
            # Pegar todos os cookies do Network
            print("[*] Extraindo cookies de sessao...")
            res_cookies = send_cmd("Network.getAllCookies")
            cookies = res_cookies.get('result', {}).get('cookies', [])
            
            if cookies:
                cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
                cookie_string = "; ".join(cookie_parts)

                cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
                with open(cookie_file_path, "w", encoding="utf-8") as f:
                    f.write(cookie_string)
                print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
            else:
                print("[-] Falha ao extrair cookies da rede.")
        else:
            print("[-] Falha no login. O botao de Logout nao foi encontrado.")
            
        ws.close()

except Exception as e:
    print(f"[-] Error: {e}")

