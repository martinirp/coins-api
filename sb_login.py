import os
import sys
import json
import time
import subprocess
import pyotp
from seleniumbase import SB

# ---------------------------------------------------------------------------
# Adaptado para rodar em proot-distro Debian dentro do Termux.
# O headless=True falha no Cloudflare Turnstile neste ambiente.
# A solução é usar Xvfb (display virtual) + headless=False.
# ---------------------------------------------------------------------------

def load_env(env_path):
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
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

# ---------------------------------------------------------------------------
# Inicia o Xvfb (display virtual) para simular uma tela sem monitor físico.
# Isso é obrigatório no proot-distro Debian — sem isso o Chrome não abre
# em modo não-headless e o headless=True não passa pelo Turnstile.
# ---------------------------------------------------------------------------
DISPLAY_NUM = ":99"
xvfb_proc = None

def start_xvfb():
    global xvfb_proc
    try:
        # Mata qualquer Xvfb anterior preso no :99
        subprocess.run(["pkill", "-f", f"Xvfb {DISPLAY_NUM}"], capture_output=True)
        time.sleep(0.5)
        # Remove o lock file se existir
        lock_file = f"/tmp/.X{DISPLAY_NUM[1:]}-lock"
        if os.path.exists(lock_file):
            os.remove(lock_file)
        xvfb_proc = subprocess.Popen(
            ["Xvfb", DISPLAY_NUM, "-screen", "0", "1280x800x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(0.5)  # Aguarda o Xvfb inicializar
        os.environ["DISPLAY"] = DISPLAY_NUM
        print(f"[+] Xvfb iniciado no display {DISPLAY_NUM}")
        return True
    except FileNotFoundError:
        print("[-] Xvfb não encontrado. Instale com: apt install xvfb")
        return False
    except Exception as e:
        print(f"[-] Falha ao iniciar Xvfb: {e}")
        return False

def stop_xvfb():
    global xvfb_proc
    if xvfb_proc:
        xvfb_proc.terminate()
        xvfb_proc = None
        print("[*] Xvfb encerrado.")

# --- Inicia o display virtual ---
xvfb_ok = start_xvfb()
if not xvfb_ok:
    print("[-] Continuando sem Xvfb — pode falhar no Cloudflare.")

print(f"[*] Iniciando SeleniumBase UC Mode para {url}...")

try:
    # headless=False é essencial para o UC Mode passar pelo Cloudflare Turnstile.
    # O Xvfb garante que não seja necessário um monitor físico.
    # --no-sandbox e --disable-dev-shm-usage são obrigatórios no proot-distro.
    with SB(
        uc=True,
        headless=False,
        browser="chrome",
        # --use-gl=swiftshader: habilita WebGL via software (sem GPU real).
        # Sem isso o --disable-gpu corta o WebGL e o Cloudflare detecta o bot.
        chromium_arg="--no-sandbox,--disable-dev-shm-usage,--use-gl=swiftshader,--ignore-gpu-blocklist,--window-size=1280,800,--disable-blink-features=AutomationControlled"
    ) as sb:
        print("[*] Acessando a pagina do Tibia...")
        # reconnect_time=10: dá mais tempo ao Cloudflare para auto-verificar o browser
        sb.uc_open_with_reconnect(url, reconnect_time=10)

        print("[*] Verificando se o Cloudflare Turnstile apareceu...")
        try:
            if hasattr(sb, 'uc_gui_handle_captcha'):
                sb.uc_gui_handle_captcha()
            else:
                sb.uc_gui_click_captcha()
            print("[+] Captcha tratado (seguindo adiante)...")
        except Exception as e:
            print(f"[*] Nota do Captcha: {e}")
            
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

            cookie_file_path = "session_cookie.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookie_string)

            print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
        else:
            sb.save_screenshot("sb_error_final.png")
            print("[-] Falha no login. Verifique sb_error_final.png para entender o que aconteceu.")
            sys.exit(1)

finally:
    stop_xvfb()
