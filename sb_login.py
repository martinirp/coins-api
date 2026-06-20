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
        time.sleep(1.5)  # Aguarda o Xvfb inicializar
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
        chromium_arg="--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--window-size=1280,800"
    ) as sb:
        print("[*] Acessando a pagina do Tibia...")
        sb.uc_open_with_reconnect(url, reconnect_time=6)

        print("[*] Verificando se o Cloudflare Turnstile apareceu...")
        try:
            sb.uc_gui_click_captcha()
            print("[+] Captcha clicado ou nao encontrado (seguindo adiante)...")
        except Exception as e:
            print(f"[*] Nota do Captcha: {e}")

        print("[*] Aguardando o carregamento dos campos de login...")
        try:
            sb.wait_for_element('input[name="loginemail"]', timeout=40)
            print("[+] Pagina de login carregada com sucesso!")
            sb.save_screenshot("sb_step1_login_ready.png")
        except Exception as e:
            sb.save_screenshot("sb_step1_error.png")
            print("[-] Timeout: Nao foi possivel carregar a tela de login. Verifique sb_step1_error.png")
            raise e

        print("[*] Preenchendo e-mail e senha...")
        sb.type('input[name="loginemail"]', email)
        sb.type('input[name="loginpassword"]', password + '\n')
        sb.save_screenshot("sb_step2_credentials_submitted.png")

        # Aguarda o campo de TOTP ou a conclusão do login
        is_totp_requested = False
        for _ in range(50):
            page_source = sb.get_page_source()
            if 'name="totp"' in page_source or "totp" in page_source:
                is_totp_requested = True
                break
            if "Logout" in page_source:
                break
            sb.sleep(0.2)

        if is_totp_requested:
            print("[*] 2FA (TOTP) solicitado! Gerando token...")
            clean_secret = totp_secret.replace(" ", "").upper()
            totp = pyotp.TOTP(clean_secret)
            totp_code = totp.now()
            print(f"[*] Token gerado: {totp_code}. Preenchendo...")
            sb.type('input[name="totp"]', totp_code + '\n')
            sb.save_screenshot("sb_step3_totp_submitted.png")

            for _ in range(50):
                if "Logout" in sb.get_page_source():
                    break
                sb.sleep(0.2)

        sb.save_screenshot("sb_step4_final.png")
        page_source = sb.get_page_source()

        if "Logout" in page_source:
            print("[+] LOGIN BEM SUCEDIDO!")

            history_url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"
            print(f"[*] Navegando ate o historico de coins: {history_url}...")
            sb.open(history_url)

            try:
                sb.wait_for_element('table', timeout=8)
            except Exception:
                pass

            sb.save_screenshot("sb_step5_coins_history.png")

            cookies = sb.get_cookies()
            cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
            cookie_string = "; ".join(cookie_parts)

            cookie_file_path = "session_cookie.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(cookie_string)

            print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
        else:
            print("[-] Falha no login. Verifique sb_step4_final.png para entender o que aconteceu.")
            sys.exit(1)

finally:
    stop_xvfb()
