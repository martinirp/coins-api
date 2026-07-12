import os
import sys
import time
import json
import pyotp
import subprocess

try:
    import websocket
    import requests
except ImportError:
    print("[*] Instalando dependencias (websocket-client e requests)...")
    os.system("pip install websocket-client requests --break-system-packages")
    import websocket
    import requests

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

def run_su(cmd):
    """Executa comando via Magisk SU"""
    return subprocess.run(["su", "-c", cmd], capture_output=True, text=True)

def setup_tunnel():
    print("[*] Criando túnel direto com o Google Chrome via socat...")
    # Mata qualquer túnel antigo
    subprocess.run(["fuser", "-k", "9222/tcp"], capture_output=True)
    
    # Socat cria uma porta 9222 TCP apontando pro socket interno do Chrome (chrome_devtools_remote)
    # Executa silenciosamente em background
    run_su("nohup socat TCP4-LISTEN:9222,bind=127.0.0.1,reuseaddr,fork ABSTRACT-CONNECT:chrome_devtools_remote >/dev/null 2>&1 &")
    time.sleep(2)

def get_tibia_ws():
    try:
        res = requests.get("http://127.0.0.1:9222/json", timeout=5)
        for tab in res.json():
            if "tibia.com" in tab.get("url", ""):
                return tab.get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None

def send_cdp(ws, method, params=None):
    if params is None:
        params = {}
    payload = {
        "id": int(time.time() * 1000) % 1000000,
        "method": method,
        "params": params
    }
    ws.send(json.dumps(payload))
    while True:
        res = json.loads(ws.recv())
        if "id" in res and res["id"] == payload["id"]:
            return res.get("result", {})

def exec_js(ws, js_code):
    return send_cdp(ws, "Runtime.evaluate", {
        "expression": js_code,
        "returnByValue": True
    })

def main():
    print("==================================================")
    print("🚀 INICIANDO HACKER MODE: CONTROLE NATIVO CHROME")
    print("==================================================")
    
    env = load_env('.env')
    email = env.get('TIBIA_EMAIL')
    password = env.get('TIBIA_PASSWORD')
    totp_secret = env.get('TIBIA_TOTP_KEY')
    
    if not email or not password:
        print("[-] Credenciais ausentes no .env")
        sys.exit(1)
        
    print("[1] Instalando 'socat' caso nao exista no sistema...")
    subprocess.run("apt-get update && apt-get install socat -y", shell=True, capture_output=True)
    
    print("[2] Acordando o celular e preparando o Chrome (aceite o pop-up de Root se aparecer)...")
    run_su("input keyevent KEYCODE_WAKEUP")
    run_su("am force-stop com.android.chrome")
    
    tibia_url = "https://www.tibia.com/account/?subtopic=accountmanagement"
    run_su(f"am start -n com.android.chrome/com.google.android.apps.chrome.Main -d '{tibia_url}'")
    
    print("[3] Aguardando o Chrome iniciar na tela do celular...")
    time.sleep(5)
    
    setup_tunnel()
    
    print("[4] Conectando na porta de desenvolvedor interna...")
    ws_url = None
    for _ in range(15):
        ws_url = get_tibia_ws()
        if ws_url:
            break
        print("    Buscando a aba do Tibia.com no Chrome...")
        time.sleep(2)
        
    if not ws_url:
        print("[-] Falha ao encontrar a aba do Tibia. O Chrome abriu na tela?")
        sys.exit(1)
        
    print(f"[+] Conectado à Matrix! Canal: {ws_url}")
    ws = websocket.create_connection(ws_url)
    
    print("[5] Aguardando bypass do Cloudflare (O hardware do seu J7 esta fazendo o trabalho)...")
    form_ready = False
    for _ in range(20):
        res = exec_js(ws, "document.querySelector('input[name=\"loginemail\"]') !== null")
        if res.get("result", {}).get("value") == True:
            form_ready = True
            break
        time.sleep(2)
        
    if not form_ready:
        print("[-] O formulario de login nao apareceu a tempo. Cloudflare segurou ou internet lenta.")
        sys.exit(1)
        
    print("[6] Cloudflare ultra-passado! Injetando Email e Senha...")
    exec_js(ws, f"document.querySelector('input[name=\"loginemail\"]').value = '{email}';")
    exec_js(ws, f"document.querySelector('input[name=\"loginpassword\"]').value = '{password}';")
    
    print("[7] Clicando em Login...")
    exec_js(ws, "document.querySelector('input[name=\"loginemail\"]').form.submit();")
    
    print("[8] Aguardando tela de Authenticator (TOTP)...")
    totp_ready = False
    logged_in = False
    for _ in range(10):
        res_totp = exec_js(ws, "document.querySelector('input[name=\"totp\"]') !== null")
        if res_totp.get("result", {}).get("value") == True:
            totp_ready = True
            break
        res_logout = exec_js(ws, "document.body.innerText.includes('Logout')")
        if res_logout.get("result", {}).get("value") == True:
            logged_in = True
            break
        time.sleep(2)
        
    if totp_ready:
        print("[9] TOTP exigido. Gerando token 2FA...")
        clean_secret = totp_secret.replace(" ", "").upper()
        totp_code = pyotp.TOTP(clean_secret).now()
        
        print(f"[*] Injetando TOTP: {totp_code}...")
        exec_js(ws, f"document.querySelector('input[name=\"totp\"]').value = '{totp_code}';")
        exec_js(ws, "document.querySelector('input[name=\"totp\"]').form.submit();")
        
        print("[10] Aguardando tela final de login...")
        for _ in range(10):
            res_logout = exec_js(ws, "document.body.innerText.includes('Logout')")
            if res_logout.get("result", {}).get("value") == True:
                logged_in = True
                break
            time.sleep(2)
            
    if logged_in:
        print("[+] =============================================")
        print("[+] SUCESSO ABSOLUTO! TIBIA INVADIDO VIA ROOT!")
        print("[+] =============================================")
        print("[11] Roubando os cookies de sessão direto da memoria do Chrome...")
        
        cookies_res = send_cdp(ws, "Network.getCookies")
        cookies = cookies_res.get("cookies", [])
        
        cookie_parts = []
        for c in cookies:
            cookie_parts.append(f"{c['name']}={c['value']}")
            
        cookie_string = "; ".join(cookie_parts)
        with open("session_cookie.txt", "w", encoding="utf-8") as f:
            f.write(cookie_string)
            
        print("[+] session_cookie.txt salvo com sucesso! A API do Tibia Coins esta viva!")
        
        print("[12] Apagando rastros e fechando o Chrome...")
        send_cdp(ws, "Target.closeTarget", {"targetId": ws_url.split("/")[-1]})
        run_su("am force-stop com.android.chrome")
    else:
        print("[-] Nao conseguiu concluir o login (Botao Logout nao apareceu).")
        sys.exit(1)

if __name__ == "__main__":
    main()
