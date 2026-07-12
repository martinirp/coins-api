import os
import sys
import json
import re
import requests
import pyotp
from bs4 import BeautifulSoup

try:
    import deathbycaptcha
except ImportError:
    print("[-] ERRO: deathbycaptcha-official nao instalado.")
    print("Rode: pip install deathbycaptcha-official --break-system-packages")
    sys.exit(1)

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

def extract_cf_challenge(html):
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', id='challenge-form')
    if not form:
        return None
        
    action = form.get('action')
    inputs = {}
    for inp in form.find_all('input', type='hidden'):
        inputs[inp.get('name')] = inp.get('value', '')
        
    sitekey_match = re.search(r"sitekey[\"']?\s*:\s*[\"']([^\"']+)[\"']", html)
    if not sitekey_match:
        sitekey_match = re.search(r"data-sitekey=[\"']([^\"']+)[\"']", html)
        
    sitekey = sitekey_match.group(1) if sitekey_match else None
    
    action_match = re.search(r"action[\"']?\s*:\s*[\"']([^\"']+)[\"']", html)
    cf_action = action_match.group(1) if action_match else "challenge"
    
    return {
        'action_url': action,
        'inputs': inputs,
        'sitekey': sitekey,
        'action': cf_action
    }

def solve_turnstile(dbc_client, sitekey, pageurl, cf_action):
    print(f"[*] Solicitando solucao do Turnstile (Sitekey: {sitekey[:10]}...) ao DBC...")
    turnstile_params = {
        "sitekey": sitekey,
        "pageurl": pageurl
    }
    if cf_action:
        turnstile_params["action"] = cf_action
        
    payload = json.dumps(turnstile_params)
    try:
        # Timeout de 120 segundos pois a API pode demorar para resolver
        captcha = dbc_client.decode(type=12, turnstile_params=payload, timeout=120)
        if captcha and captcha.get("text"):
            print("[+] Token Turnstile recebido com sucesso!")
            return captcha["text"]
    except Exception as e:
        print(f"[-] Erro na API do DeathByCaptcha: {e}")
    return None

def main():
    print("==================================================")
    print("🚀 INICIANDO LOGIN COM DEATHBYCAPTCHA (TURNSTILE)")
    print("==================================================")
    
    env = load_env('.env')
    email = env.get('TIBIA_EMAIL')
    password = env.get('TIBIA_PASSWORD')
    totp_secret = env.get('TIBIA_TOTP_KEY')
    dbc_user = env.get('DBC_USERNAME')
    dbc_pass = env.get('DBC_PASSWORD')

    if not email or not password or not totp_secret:
        print("[-] ERRO: Credenciais do Tibia ausentes no .env.")
        sys.exit(1)
        
    if not dbc_user or not dbc_pass:
        print("[-] ERRO: Credenciais do DeathByCaptcha ausentes no .env.")
        print("Adicione DBC_USERNAME=seu_usuario e DBC_PASSWORD=sua_senha no .env")
        sys.exit(1)

    print("[1] Conectando ao DeathByCaptcha...")
    try:
        dbc_client = deathbycaptcha.HttpClient(dbc_user, dbc_pass)
        balance = dbc_client.get_balance()
        print(f"[+] Saldo DBC: {balance} US cents")
    except Exception as e:
        print(f"[-] Erro ao conectar no DBC: Verifique suas credenciais. Erro: {e}")
        sys.exit(1)

    url = "https://www.tibia.com/account/?subtopic=accountmanagement"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })
    
    print("[2] Acessando a pagina de login do Tibia...")
    res = session.get(url, timeout=20)
    print(f"[*] Status HTTP Inicial: {res.status_code}")
    
    # 1. Burlar o bloqueio inicial do Cloudflare (IUAM)
    if res.status_code in [403, 503] or 'challenge-form' in res.text:
        print("[!] O Cloudflare bloqueou o acesso inicial. Analisando o desafio...")
        cf_data = extract_cf_challenge(res.text)
        
        if not cf_data or not cf_data['sitekey']:
            print("[-] Falha ao encontrar a Sitekey do Cloudflare no HTML.")
            sys.exit(1)
            
        token = solve_turnstile(dbc_client, cf_data['sitekey'], url, cf_data['action'])
        if not token:
            print("[-] Falha ao resolver Turnstile do Cloudflare inicial.")
            sys.exit(1)
            
        submit_url = url
        if cf_data['action_url']:
            if cf_data['action_url'].startswith('/'):
                submit_url = "https://www.tibia.com" + cf_data['action_url']
            else:
                submit_url = cf_data['action_url']
                
        cf_payload = cf_data['inputs']
        cf_payload['cf-turnstile-response'] = token
        
        print("[3] Enviando token Turnstile para o Cloudflare...")
        res = session.post(submit_url, data=cf_payload, timeout=20)
        print(f"[*] Status HTTP pos-Cloudflare: {res.status_code}")
        
    if res.status_code != 200:
        print("[-] Falha ao passar pelo Cloudflare. Status não é 200.")
        sys.exit(1)
        
    print("[4] Pagina de login carregada! Preenchendo formulario...")
    
    soup = BeautifulSoup(res.text, 'html.parser')
    login_data = {'loginemail': email, 'loginpassword': password}
    
    login_form = None
    for f in soup.find_all('form'):
        if f.find('input', {'name': 'loginemail'}):
            login_form = f
            break
            
    if not login_form:
        print("[-] Formulario de login nao encontrado no HTML.")
        sys.exit(1)
        
    for hidden in login_form.find_all('input', type='hidden'):
        if hidden.get('name'):
            login_data[hidden.get('name')] = hidden.get('value', '')
            
    post_url = login_form.get('action') or url
    
    # 2. Burlar o Turnstile que fica no botao de login do Tibia
    sitekey_match = re.search(r"data-sitekey=[\"']([^\"']+)[\"']", str(login_form))
    if not sitekey_match:
        sitekey_match = re.search(r"sitekey[\"']?\s*:\s*[\"']([^\"']+)[\"']", res.text)
        
    if sitekey_match:
        tibia_sitekey = sitekey_match.group(1)
        print(f"[!] O formulario de login tambem tem um Turnstile invisível!")
        token = solve_turnstile(dbc_client, tibia_sitekey, url, "login")
        if token:
            login_data['cf-turnstile-response'] = token
    
    print("[5] Enviando E-mail e Senha para o Tibia...")
    res = session.post(post_url, data=login_data, timeout=20)
    print(f"[*] Status HTTP Login: {res.status_code}")
    
    soup = BeautifulSoup(res.text, 'html.parser')
    
    if "Logout" in res.text:
        print("[+] Logado com sucesso (Sem 2FA)!")
    elif 'name="totp"' in res.text or 'totp' in res.text:
        print("[6] Conta protegida por Authenticator (2FA). Gerando token...")
        clean_secret = totp_secret.replace(" ", "").upper()
        totp_code = pyotp.TOTP(clean_secret).now()
        
        totp_data = {'totp': totp_code}
        totp_form = None
        for f in soup.find_all('form'):
            if f.find('input', {'name': 'totp'}):
                totp_form = f
                break
                
        if totp_form:
            for hidden in totp_form.find_all('input', type='hidden'):
                if hidden.get('name'):
                    totp_data[hidden.get('name')] = hidden.get('value', '')
            post_url = totp_form.get('action') or url
        else:
            post_url = url
            
        print(f"[7] Enviando token TOTP ({totp_code})...")
        res = session.post(post_url, data=totp_data, timeout=20)
        print(f"[*] Status HTTP TOTP: {res.status_code}")
    else:
        print("[-] Falha: Tibia nao confirmou o login e nao pediu 2FA.")
        sys.exit(1)
        
    if "Logout" in res.text:
        print("[+] =============================================")
        print("[+] SUCESSO ABSOLUTO! TIBIA HACKEADO VIA DBC!")
        print("[+] =============================================")
        
        cookie_parts = [f"{c.name}={c.value}" for c in session.cookies]
        cookie_string = "; ".join(cookie_parts)
        
        with open("session_cookie.txt", "w", encoding="utf-8") as f:
            f.write(cookie_string)
            
        print("[+] Cookie de sessao salvo com sucesso. O Bot esta pronto.")
    else:
        print("[-] Algo deu errado no ultimo passo. Login falhou.")
        sys.exit(1)

if __name__ == "__main__":
    main()
