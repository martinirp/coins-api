import os
import sys
import json
import time
import shutil
import platform
import subprocess
import pyotp

# Imports extras para o modo Termux (Selenium puro)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
        # MODO TERMUX ADB (Selenium Puro)
        print("[*] Ambiente Termux detectado. Conectando ao Chrome do Android via ADB (porta 9222)...")
        options = Options()
        options.debugger_address = "127.0.0.1:9222"
        
        driver = webdriver.Chrome(options=options)
        wait = WebDriverWait(driver, 30)
        
        print(f"[*] Navegando para: {url}")
        driver.get(url)
        
        print("[*] Aguardando a pagina carregar (se o Cloudflare parar, resolva no celular manualmente e eu continuo!)")
        email_input = wait.until(EC.presence_of_element_located((By.NAME, "loginemail")))
        print("[+] Pagina de login pronta!")
        
        print("[*] Preenchendo credenciais...")
        email_input.clear()
        email_input.send_keys(email)
        
        pass_input = driver.find_element(By.NAME, "loginpassword")
        pass_input.clear()
        pass_input.send_keys(password)
        pass_input.send_keys(Keys.RETURN)
        
        # Espera carregar proxima tela (totp ou sucesso)
        time.sleep(3)
        
        page_source = driver.page_source
        if 'name="totp"' in page_source or "totp" in page_source:
            print("[*] 2FA (TOTP) solicitado! Gerando token...")
            totp_code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
            print(f"[*] Token gerado: {totp_code}. Inserindo...")
            totp_input = driver.find_element(By.NAME, "totp")
            totp_input.clear()
            totp_input.send_keys(totp_code)
            totp_input.send_keys(Keys.RETURN)
            time.sleep(3)
            
        page_source = driver.page_source
        if "Logout" in page_source:
            print("[+] LOGIN BEM SUCEDIDO!")
            print(f"[*] Navegando ate historico: {history_url}")
            driver.get(history_url)
            time.sleep(2) # Aguarda historico carregar um pouco
            
            cookies = driver.get_cookies()
            cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
            cookie_string = "; ".join(cookie_parts)

            cookie_file_path = os.path.join(SCRIPT_DIR, "session_cookie.txt")
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookie_string)
            print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
        else:
            print("[-] Falha no login. Nao encontrei o botao de Logout.")
            sys.exit(1)

except Exception as e:
    print(f"[-] Error: {e}")

