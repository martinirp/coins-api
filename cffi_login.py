import os
import sys
import pyotp
import time
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests
except ImportError:
    print("[-] ERRO: curl_cffi nao instalado. Rode: pip install curl_cffi")
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

def main():
    print("==================================================")
    print("🚀 INICIANDO LOGIN VIA HTTP PURO (curl_cffi)")
    print("==================================================")
    
    print("[1] Carregando credenciais do .env...")
    env = load_env('.env')
    email = env.get('TIBIA_EMAIL')
    password = env.get('TIBIA_PASSWORD')
    totp_secret = env.get('TIBIA_TOTP_KEY')

    if not email or not password or not totp_secret:
        print("[-] ERRO: Credenciais ausentes no .env.")
        sys.exit(1)

    url = "https://www.tibia.com/account/?subtopic=accountmanagement"
    
    print("[2] Configurando o bypasser (impersonate='chrome120')...")
    session = requests.Session(impersonate="chrome120")
    
    print("[3] Fazendo o primeiro GET na pagina principal para pegar os formulários ocultos...")
    try:
        res = session.get(url, timeout=20)
        print(f"[V] Resposta do GET: HTTP {res.status_code}")
    except Exception as e:
        print(f"[-] Erro de conexao: {e}")
        sys.exit(1)

    if res.status_code != 200:
        print("[-] Falha inicial! O site retornou um erro.")
        print(res.text[:500])
        sys.exit(1)

    if 'cf-turnstile' in res.text or 'Verifying you are human' in res.text:
        print("[-] AVISO: O Cloudflare detectou o acesso e forçou o Turnstile (JavaScript).")
        print("[-] Infelizmente o formulário requer o token do Turnstile.")
        sys.exit(1)

    print("[4] Cloudflare ultrapassado sem Captcha! Lendo o HTML da pagina de login...")
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
        print("[V] Formulario de login encontrado. Extraindo campos escondidos (hidden)...")
        for hidden in login_form.find_all('input', type='hidden'):
            if hidden.get('name'):
                login_data[hidden.get('name')] = hidden.get('value', '')
        post_url = login_form.get('action') or url
    else:
        print("[!] Nao achou o formulário exatamente, vamos tentar forçar os dados.")
        post_url = url
        
    print("[5] Enviando POST com E-mail e Senha...")
    res = session.post(post_url, data=login_data, timeout=20)
    print(f"[V] Resposta do POST de Login: HTTP {res.status_code}")
    
    soup = BeautifulSoup(res.text, 'html.parser')
    
    if "Logout" in res.text:
        print("[V] Logado sem precisar de 2FA!")
    elif 'name="totp"' in res.text or 'totp' in res.text:
        print("[6] Site exigiu o código de Autenticacao (TOTP)!")
        clean_secret = totp_secret.replace(" ", "").upper()
        totp = pyotp.TOTP(clean_secret)
        totp_code = totp.now()
        print(f"[V] Codigo TOTP gerado com sucesso.")
        
        totp_data = {'totp': totp_code}
        totp_form = None
        for f in soup.find_all('form'):
            if f.find('input', {'name': 'totp'}):
                totp_form = f
                break
                
        if totp_form:
            print("[7] Preparando campos ocultos do 2FA...")
            for hidden in totp_form.find_all('input', type='hidden'):
                if hidden.get('name'):
                    totp_data[hidden.get('name')] = hidden.get('value', '')
            post_url = totp_form.get('action') or url
        else:
            post_url = url
            
        print("[8] Enviando POST com o codigo 2FA...")
        res = session.post(post_url, data=totp_data, timeout=20)
        print(f"[V] Resposta do envio do 2FA: HTTP {res.status_code}")
    else:
        print("[-] Falha ao logar. Nao pediu 2FA nem confirmou o login.")
        with open("erro_cffi_login.html", "w", encoding="utf-8") as f:
            f.write(res.text)
        print("[-] Pagina HTML salva em erro_cffi_login.html para depuracao.")
        sys.exit(1)
        
    print("[9] Checando confirmacao de login...")
    if "Logout" in res.text:
        print("[+] =============================================")
        print("[+] SUCESSO TOTAL! LOGIN FEITO VIA HTTP PURO!")
        print("[+] =============================================")
        print("[10] Lendo os cookies gerados e gravando em arquivo...")
        
        cookie_parts = []
        for c in session.cookies.jar:
            cookie_parts.append(f"{c.name}={c.value}")
        
        cookie_string = "; ".join(cookie_parts)
        with open("session_cookie.txt", "w", encoding="utf-8") as f:
            f.write(cookie_string)
            
        print("[+] Arquivo session_cookie.txt atualizado com sucesso e pronto para uso!")
    else:
        print("[-] Ocorreu algo estranho. O botao de 'Logout' nao apareceu apos o envio.")
        sys.exit(1)

if __name__ == "__main__":
    main()
