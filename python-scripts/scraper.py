import os
import sys
import json
import hashlib
import re
from bs4 import BeautifulSoup
from scrapling.fetchers import Fetcher


def parse_cookie_str(cookie_str):
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cookie_path = os.path.join(base_dir, "session_cookie.txt")
    url = "https://www.tibia.com/account/?subtopic=accountmanagement&page=tibiacoinshistory"

    if not os.path.exists(cookie_path):
        print(json.dumps({"error": "session_cookie.txt not found"}), flush=True)
        sys.exit(1)

    with open(cookie_path, "r", encoding="utf-8") as f:
        cookie_str = f.read().strip()

    cookies = parse_cookie_str(cookie_str)

    try:
        response = Fetcher.get(
            url,
            cookies=cookies,
            impersonate="chrome",
            stealthy_headers=True,
            timeout=25,
        )
        if response.status != 200:
            print(json.dumps({"error": f"HTTP {response.status}"}), flush=True)
            sys.exit(1)

        html = response.body.decode("utf-8", errors="replace")

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

        rows = target_table.find_all("tr")[1:]
        transactions = []

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 5:
                continue

            date = re.sub(r"\s+", " ", cols[1].get_text()).strip()
            description = re.sub(r"\s+", " ", cols[2].get_text()).strip()
            amount_str = cols[4].get_text().strip()

            amount_clean = "".join([c for c in amount_str if c.isdigit() or c in ("+", "-")])
            if not amount_clean:
                continue
            try:
                amount = int(amount_clean)
            except ValueError:
                continue

            combined = f"{date}-{description}-{amount}"
            tx_id = hashlib.md5(combined.encode("utf-8")).hexdigest()

            character = "System"
            desc_lower = description.lower()
            if "gifted to" in desc_lower:
                character = re.split(r"\s+gifted to\s+", description, flags=re.IGNORECASE)[0].strip()
            elif "gifted from" in desc_lower:
                parts = re.split(r"\bfrom\s+", description, flags=re.IGNORECASE)
                character = parts[1].strip() if len(parts) > 1 else "System"
            elif "sent to" in desc_lower:
                parts = re.split(r"\bto\s+", description, flags=re.IGNORECASE)
                character = parts[1].strip() if len(parts) > 1 else "System"

            character = re.sub(r"\s+", " ", character).strip()

            transactions.append({
                "id": tx_id,
                "date": date,
                "description": description,
                "character": character,
                "amount": amount,
            })

        print(json.dumps({"status": "success", "transactions": transactions}), flush=True)

    except Exception as e:
        print(json.dumps({"error": str(e)}), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()