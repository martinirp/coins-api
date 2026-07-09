import sys
import os
import json
import shutil
import tempfile
import threading
import concurrent.futures
import pyotp
from seleniumbase import SB

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ACCOUNT_URL = "https://www.tibia.com/account/?subtopic=accountmanagement"

# ── Lock para escalonar a inicialização dos browsers ──────────────────────────
# Evita race condition no patcher do ChromeDriver (undetected-chromedriver).
# Cada browser aguarda o anterior ter inicializado antes de abrir.
_INIT_STAGGER  = 2.5  # segundos mínimos entre cada abertura de browser
_init_lock     = threading.Lock()
_last_init_ts  = [0.0]


def log(msg):
    print(msg, flush=True)


def _staggered_browser_start():
    """Garante que cada browser é aberto com pelo menos _INIT_STAGGER de intervalo."""
    import time
    with _init_lock:
        now  = time.time()
        wait = _last_init_ts[0] + _INIT_STAGGER - now
        if wait > 0:
            time.sleep(wait)
        _last_init_ts[0] = time.time()


# ── Helpers de página ──────────────────────────────────────────────────────────

def _is_logged_in(sb):
    try:
        page = sb.get_page_source()
        return "Logout" in page or "Manage Account" in page
    except Exception:
        return False


def _wait_for_page(sb, timeout=40):
    """Aguarda indicador de login ou form de login. Retorna 'logged_in', 'login_form' ou 'unknown'."""
    try:
        sb.wait_for_element_present(
            'input[name="loginemail"], input[value="Manage Account"], a[href*="action=logout"]',
            timeout=timeout
        )
    except Exception:
        pass
    try:
        page = sb.get_page_source()
        if "Logout" in page or "Manage Account" in page:
            return "logged_in"
        if 'name="loginemail"' in page:
            return "login_form"
    except Exception:
        pass
    return "unknown"


def _wait_page_ready(sb, timeout=15):
    """Aguarda document.readyState === 'complete'."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if sb.execute_script("return document.readyState;") == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


# ── Login ──────────────────────────────────────────────────────────────────────

def _do_login(sb, email, password, totp_secret, label):
    """Login completo (browser sempre fresh). Retorna True se bem-sucedido."""
    sb.uc_open_with_reconnect(ACCOUNT_URL, reconnect_time=3)

    state = _wait_for_page(sb, timeout=45)

    if state == "unknown":
        try:
            sb.uc_gui_click_captcha()
        except Exception:
            pass
        state = _wait_for_page(sb, timeout=20)

    if state == "logged_in":
        return True
    if state != "login_form":
        return False

    try:
        sb.wait_for_element_present('input[name="loginemail"]', timeout=10)
    except Exception:
        return False

    sb.type('input[name="loginemail"]', email)
    sb.type('input[name="loginpassword"]', password + '\n')

    totp_appeared = False
    try:
        sb.wait_for_element_present(
            'input[name="totp"], a[href*="action=logout"], input[value="Manage Account"]',
            timeout=20
        )
        totp_appeared = 'name="totp"' in sb.get_page_source()
    except Exception:
        pass

    if totp_appeared:
        if not totp_secret:
            return False
        import time as _t
        for attempt in range(2):
            remaining = 30 - (int(_t.time()) % 30)
            if remaining <= 4:
                log(f"  [TOTP] Aguardando nova janela ({remaining}s)...")
                _t.sleep(remaining + 0.5)
            
            code = pyotp.TOTP(totp_secret.replace(" ", "").upper()).now()
            sb.clear('input[name="totp"]')
            sb.type('input[name="totp"]', code + '\n')
            
            try:
                # Espera a página recarregar com sucesso ou falha
                sb.wait_for_element_present(
                    'a[href*="action=logout"], input[value="Manage Account"], input[name="totp"]',
                    timeout=15
                )
            except Exception:
                pass
            
            src = sb.get_page_source()
            if 'The token is invalid!' in src or 'name="totp"' in src:
                if 'The token is invalid!' in src:
                    log(f"  [TOTP] Token inválido! Tentando novamente ({attempt+1}/2)...")
                # Aguarda o próximo ciclo para ter certeza de gerar um código diferente
                rem = 30 - (int(_t.time()) % 30)
                _t.sleep(rem + 0.5)
                continue
            else:
                break

    return _is_logged_in(sb)


# ── Account Management ─────────────────────────────────────────────────────────

def _navigate_to_account_management(sb):
    """Clica em Manage Account via JS (instantâneo) e fecha banner de cookies."""
    clicked = sb.execute_script("""
        var btn = document.querySelector('input[value="Manage Account"]');
        if (btn) { btn.click(); return true; }
        return false;
    """)
    if clicked:
        _wait_page_ready(sb, timeout=15)

    sb.execute_script("""
        var btns = document.querySelectorAll('button, input');
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].textContent || btns[i].value || '').toLowerCase();
            if (t.includes('accept all') || t.includes('aceitar')) {
                btns[i].click(); break;
            }
        }
    """)


def _remove_all_trusted_devices(sb, label):
    """Detecta e clica Remove All via JS. Retorna dict com status."""
    _wait_page_ready(sb, timeout=15)

    remove_clicked = sb.execute_script("""
        var selectors = ['input[value="Remove All"]', 'input.BigButtonText[type="submit"]', 'input[type="submit"]'];
        for (var i = 0; i < selectors.length; i++) {
            var btns = document.querySelectorAll(selectors[i]);
            for (var j = 0; j < btns.length; j++) {
                if (btns[j].value && btns[j].value.toLowerCase().includes('remove all')) {
                    btns[j].scrollIntoView({ behavior: 'instant', block: 'center' });
                    btns[j].click();
                    return true;
                }
            }
        }
        return false;
    """)

    if not remove_clicked:
        return {"account": label, "status": "skipped", "reason": "no_trusted_devices"}

    # Aguarda confirmação (máx 3s)
    try:
        sb.wait_for_text_visible("No trusted devices", timeout=3)
        return {"account": label, "status": "success"}
    except Exception:
        pass

    page = sb.get_page_source()
    if "No trusted devices" in page or "removed all of your trusted devices" in page.lower():
        return {"account": label, "status": "success"}
    return {"account": label, "status": "done_unconfirmed"}


# ── Worker ─────────────────────────────────────────────────────────────────────

def _run_account(account, login_sem, headless=False):
    """
    Pipeline por semáforo:
    1. Adquire slot de login (máx max_workers simultâneos)
    2. Abre browser (com stagger para evitar race condition do ChromeDriver)
    3. Faz login
    4. Libera slot → próximo browser já começa a logar em paralelo
    5. Remove trusted devices
    6. Fecha browser (sem logout)
    """
    label    = account.get("name", account.get("email", "?"))
    temp_dir = tempfile.mkdtemp(prefix="mauth_")

    # Aguarda slot de login disponível
    login_sem.acquire()
    released = False

    def _release():
        nonlocal released
        if not released:
            released = True
            login_sem.release()

    try:
        # Abre browser com stagger (evita conflito no patcher do chromedriver)
        _staggered_browser_start()
        log(f"[*] Iniciando: {label}")

        with SB(
            uc=True,
            headless=headless,
            browser="chrome",
            user_data_dir=temp_dir,
            chromium_arg="--no-sandbox,--disable-dev-shm-usage,--disable-gpu"
        ) as sb:
            logged = _do_login(sb, account.get("email", ""), account.get("password", ""),
                               account.get("totp_secret", ""), label)

            # ★ Login concluído → libera slot para o próximo browser já começar login
            _release()

            if not logged:
                return {"account": label, "status": "error", "reason": "login_failed"}

            log(f"  [✓] {label}: logado.")
            _navigate_to_account_management(sb)
            result = _remove_all_trusted_devices(sb, label)
            log(f"  [+] {label}: {result['status']}")
            return result

    except Exception as e:
        _release()
        log(f"[-] {label}: {e}")
        return {"account": label, "status": "error", "reason": str(e)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main(max_workers=3, headless=False):
    try:
        data_str = sys.stdin.read()
        accounts = json.loads(data_str)
    except Exception as e:
        print(json.dumps({"error": f"JSON inválido: {e}"}), flush=True)
        sys.exit(1)

    if not isinstance(accounts, list) or len(accounts) == 0:
        print(json.dumps({"error": "Lista de contas vazia ou inválida"}), flush=True)
        sys.exit(1)

    total     = len(accounts)
    n_workers = min(max_workers, total)
    results   = []

    log(f"[*] {total} conta(s) | {n_workers} login(s) em paralelo (pipeline) | Headless: {headless}")

    # Semáforo limita logins simultâneos; Remove All sobrepõe com próximos logins
    login_sem = threading.Semaphore(n_workers)

    # Thread pool com 1 thread por conta (cada uma controla seu próprio browser)
    with concurrent.futures.ThreadPoolExecutor(max_workers=total) as executor:
        futures = [executor.submit(_run_account, acc, login_sem, headless) for acc in accounts]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({"status": "error", "reason": str(e)})

    print(json.dumps({"status": "finished", "results": results}), flush=True)


if __name__ == "__main__":
    workers = 3
    headless = False
    if "--workers" in sys.argv:
        idx = sys.argv.index("--workers")
        if idx + 1 < len(sys.argv):
            try:
                workers = int(sys.argv[idx + 1])
            except ValueError:
                pass
    if "--headless" in sys.argv:
        headless = True
    main(workers, headless)
