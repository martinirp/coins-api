import os
import sys
import json
import hashlib
import re
import requests
from bs4 import BeautifulSoup

cookie_path = "session_cookie.txt"
url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"

if not os.path.exists(cookie_path):
    print(json.dumps({"error": "session_cookie.txt not found"}), flush=True)
    sys.exit(1)

with open(cookie_path, "r", encoding="utf-8") as f:
    cookie_str = f.read().strip()

print(f"[scraper] Cookie carregado ({len(cookie_str)} chars)", file=sys.stderr, flush=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Cookie": cookie_str
}

try:
    print("[scraper] Iniciando requisicao HTTP...", file=sys.stderr, flush=True)
    response = requests.get(url, headers=headers, timeout=20)
    print(f"[scraper] Resposta recebida: HTTP {response.status_code}", file=sys.stderr, flush=True)
    if response.status_code != 200:
        print(json.dumps({"error": f"HTTP {response.status_code}"}), flush=True)
        sys.exit(1)
        
    html = response.text
    
    # Verifica se fomos redirecionados para a tela de login
    if "loginemail" in html or "Log In" in html or "forgot_password" in html:
        print(json.dumps({"error": "session_expired"}), flush=True)
        sys.exit(0)
        
    soup = BeautifulSoup(html, "html.parser")
    
    target_table = None
    for table in soup.find_all("table"):
        table_text = table.get_text().lower()
        if "date" in table_text and ("balance" in table_text or "description" in table_text):
            target_table = table
            break
            
    if not target_table:
        print(json.dumps({"error": "table_not_found"}), flush=True)
        sys.exit(0)
        
    # Extrai linhas (pula o cabeçalho)
    rows = target_table.find_all("tr")[1:]
    transactions = []
    
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue
            
        date = re.sub(r'\s+', ' ', cols[1].get_text()).strip()
        description = re.sub(r'\s+', ' ', cols[2].get_text()).strip()
        amount_str = cols[4].get_text().strip()
        
        # Limpa o valor para conter apenas número e sinal +/-
        amount_clean = "".join([c for c in amount_str if c.isdigit() or c in ("+", "-")])
        if not amount_clean:
            continue
            
        try:
            amount = int(amount_clean)
        except ValueError:
            continue
            
        # Gera o hash MD5 ID idêntico ao monitor.js
        combined = f"{date}-{description}-{amount}"
        tx_id = hashlib.md5(combined.encode("utf-8")).hexdigest()
        
        # Parseia o nome do personagem envolvido na transação
        character = 'System'
        desc_lower = description.lower()
        if 'gifted to' in desc_lower:
            character = re.split(r'\s+gifted to\s+', description, flags=re.IGNORECASE)[0].strip()
        elif 'gifted from' in desc_lower:
            parts = re.split(r'\bfrom\s+', description, flags=re.IGNORECASE)
            character = parts[1].strip() if len(parts) > 1 else 'System'
        elif 'sent to' in desc_lower:
            parts = re.split(r'\bto\s+', description, flags=re.IGNORECASE)
            character = parts[1].strip() if len(parts) > 1 else 'System'
            
        character = re.sub(r'\s+', ' ', character).strip()
        
        transactions.append({
            "id": tx_id,
            "date": date,
            "description": description,
            "character": character,
            "amount": amount
        })
        
    print(json.dumps({"status": "success", "transactions": transactions}), flush=True)

except Exception as e:
    print(json.dumps({"error": str(e)}), flush=True)
    sys.exit(1)
