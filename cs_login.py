import os
import sys
import pyotp
import cloudscraper
from bs4 import BeautifulSoup

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

def main():
    print("==================================================")
    print("🚀 INICIANDO LOGIN AUTOMATICO VIA CLOUDSCRAPER")
    print("==================================================")
    
    env = load_env('.env')
    email = env.get('TIBIA_EMAIL')
    password = env.get('TIBIA_PASSWORD')
    totp_secret = env.get('TIBIA_TOTP_KEY')

    if not email or not password or not totp_secret:
        print("[-] ERRO: Credenciais ausentes no .env.")
        sys.exit(1)

    url = "https://www.tibia.com/account/?subtopic=accountmanagement"
    
    # Criando o scraper. Como sabemos que o cloudscraper nao trava no seu proot (pois o scraper.py o usa)
    scraper = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    })
    
    print("[1] Acessando a pagina de login...")
    try:
        res = scraper.get(url, timeout=20)
        print(f"[V] Status: HTTP {res.status_code}")
    except Exception as e:
        print(f"[-] Erro de conexao: {e}")
        sys.exit(1)

    if res.status_code != 200:
        print("[-] O site bloqueou o acesso inicial.")
        sys.exit(1)

    if 'cf-turnstile' in res.text or 'Verifying you are human' in res.text:
        print("[-] AVISO: O Cloudflare exigiu Turnstile via JavaScript na pagina principal.")
        print("[-] O cloudscraper puro nao resolve esse tipo de Captcha do Turnstile.")
        sys.exit(1)

    print("[2] Extraindo campos de seguranca da pagina...")
    soup = BeautifulSoup(res.text, 'html.parser')
    
    login_data = {
        'loginemail': email,
        'loginpassword': password,
    }
    
    login_form = None
    for f in soup.find_all('form'):
        if f.find('input', {'name': 'loginemail'}):
            login_form = f
            break
            
    if login_form:
        for hidden in login_form.find_all('input', type='hidden'):
            if hidden.get('name'):
                login_data[hidden.get('name')] = hidden.get('value', '')
        post_url = login_form.get('action') or url
    else:
        post_url = url
        
    print("[3] Enviando POST com E-mail e Senha...")
    res = scraper.post(post_url, data=login_data, timeout=20)
    print(f"[V] Status do Login: HTTP {res.status_code}")
    
    soup = BeautifulSoup(res.text, 'html.parser')
    
    if "Logout" in res.text:
        print("[V] Logado sem precisar de 2FA!")
    elif 'name="totp"' in res.text or 'totp' in res.text:
        print("[4] O site exigiu o TOTP (2FA). Gerando...")
        clean_secret = totp_secret.replace(" ", "").upper()
        totp = pyotp.TOTP(clean_secret)
        totp_code = totp.now()
        
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
            
        print(f"[5] Enviando codigo TOTP: {totp_code}...")
        res = scraper.post(post_url, data=totp_data, timeout=20)
        print(f"[V] Status do TOTP: HTTP {res.status_code}")
    else:
        print("[-] Falha ao logar. Nao pediu 2FA e nao logou.")
        with open("erro_cs_login.html", "w", encoding="utf-8") as f:
            f.write(res.text)
        sys.exit(1)
        
    print("[6] Checando se o login foi concluido com sucesso...")
    if "Logout" in res.text:
        print("[+] =============================================")
        print("[+] SUCESSO TOTAL! LOGIN AUTOMATICO CONCLUIDO!")
        print("[+] =============================================")
        
        cookie_parts = []
        for c in scraper.cookies:
            cookie_parts.append(f"{c.name}={c.value}")
        
        cookie_string = "; ".join(cookie_parts)
        with open("session_cookie.txt", "w", encoding="utf-8") as f:
            f.write(cookie_string)
            
        print("[+] Cookies atualizados automaticamente no celular!")
    else:
        print("[-] Nao conseguiu confirmar o login.")
        sys.exit(1)

if __name__ == "__main__":
    main()
