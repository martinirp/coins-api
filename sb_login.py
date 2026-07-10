import os
import sys
import json
import time
import datetime
import pyotp
from seleniumbase import SB

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

# Configurações de credenciais
env = load_env('.env')
email = env.get('TIBIA_EMAIL')
password = env.get('TIBIA_PASSWORD')
totp_secret = env.get('TIBIA_TOTP_KEY')

if not email or not password or not totp_secret:
    print("[-] ERRO: Credenciais ou chave TOTP ausentes no arquivo .env.")
    sys.exit(1)

url = "https://www.tibia.com/account/?subtopic=accountmanagement"
print(f"[*] Iniciando SeleniumBase UC Mode para {url}...")

# UC=True ativa o Undetected-Chromedriver para burlar Cloudflare Turnstile
# headless=True garante que rode 100% invisível em segundo plano sem abrir janelas de navegador
# chromium_arg="--no-sandbox,--disable-dev-shm-usage" é essencial para rodar no Termux PRoot
with SB(uc=True, headless=True, browser="chrome", chromium_arg="--no-sandbox,--disable-dev-shm-usage") as sb:
    print("[*] Acessando a pagina do Tibia...")
    sb.uc_open_with_reconnect(url, reconnect_time=4)
    
    print("[*] Verificando se o Cloudflare Turnstile apareceu...")
    try:
        # Tenta clicar no checkbox do Turnstile se ele aparecer na tela
        sb.uc_gui_click_captcha()
        print("[+] Captcha clicado ou nao encontrado (seguindo adiante)...")
    except Exception as e:
        print(f"[*] Nota do Captcha: {e}")
        
    print("[*] Aguardando o carregamento dos campos de login...")
    try:
        sb.wait_for_element('input[name="loginemail"]', timeout=30)
        print("[+] Pagina de login carregada com sucesso!")
        sb.save_screenshot("sb_step1_login_ready.png")
    except Exception as e:
        sb.save_screenshot("sb_step1_error.png")
        print("[-] Timeout: Nao foi possivel carregar a tela de login. Verifique sb_step1_error.png")
        raise e
        
    print("[*] Preenchendo e-mail e senha...")
    sb.type('input[name="loginemail"]', email)
    # Enviamos a senha seguida de \n para submeter o formulário pressionando Enter
    sb.type('input[name="loginpassword"]', password + '\n')
    sb.save_screenshot("sb_step2_credentials_submitted.png")
    
    # Aguarda dinamicamente o carregamento do campo de 2FA (TOTP) ou o login concluir (até 5 segundos)
    is_totp_requested = False
    for _ in range(25):
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
        offset_hours = float(env.get('TIME_OFFSET_HOURS', '0'))
        if offset_hours != 0:
            print(f"[*] Aplicando ajuste de relogio de {offset_hours} horas para o TOTP...")
        adjusted_time = datetime.datetime.now() + datetime.timedelta(hours=offset_hours)
        totp_code = totp.at(adjusted_time)
        print(f"[*] Token gerado: {totp_code}. Preenchendo...")
        # Enviamos o token seguido de \n para submeter pressionando Enter
        sb.type('input[name="totp"]', totp_code + '\n')
        sb.save_screenshot("sb_step3_totp_submitted.png")
        
        # Aguarda dinamicamente a conclusão do login (até 5 segundos)
        for _ in range(25):
            if "Logout" in sb.get_page_source():
                break
            sb.sleep(0.2)
        
    sb.save_screenshot("sb_step4_final.png")
    page_source = sb.get_page_source()
    
    if "Logout" in page_source:
        print("[+] LOGIN BEM SUCEDIDO!")
        
        # Navega até o histórico de coins
        history_url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"
        print(f"[*] Navegando ate o historico de coins: {history_url}...")
        sb.open(history_url)
        
        # Aguarda a tabela de histórico carregar na tela
        try:
            sb.wait_for_element('table', timeout=6)
        except Exception:
            pass
            
        sb.save_screenshot("sb_step5_coins_history.png")
        
        # Extrai os cookies e formata para o session_cookie.txt
        cookies = sb.get_cookies()
        cookie_parts = []
        for cookie in cookies:
            cookie_parts.append(f"{cookie['name']}={cookie['value']}")
        cookie_string = "; ".join(cookie_parts)
        
        cookie_file_path = "session_cookie.txt"
        with open(cookie_file_path, "w", encoding="utf-8") as f:
            f.write(cookie_string)
            
        print(f"[+] Cookies de sessao salvos com sucesso em {cookie_file_path}!")
    else:
        print("[-] Falha no login. Verifique sb_step4_final.png para entender o que aconteceu.")
