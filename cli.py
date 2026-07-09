import sys
import json
import sb_login
import remove_trusted_devices
import scraper

import os

# ─── Diretório persistente para o chromedriver ─────────────────────────────
# O SeleniumBase usa o CWD para salvar o chromedriver baixado.
# Ao usar um diretório fixo em AppData, o download só acontece uma vez.
_DRIVER_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "mauth-drivers")
os.makedirs(_DRIVER_DIR, exist_ok=True)

def _set_persistent_cwd():
    """Muda o CWD para o diretório persistente antes de qualquer chamada ao SeleniumBase."""
    os.chdir(_DRIVER_DIR)

def main():
    # Garante que o diretório de trabalho seja o do executável para paths relativos
    exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing command argument"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "login":
        os.chdir(exe_dir)
        sb_login.main()
    elif command == "remove":
        workers = 6
        if "--workers" in sys.argv:
            idx = sys.argv.index("--workers")
            if idx + 1 < len(sys.argv):
                workers = int(sys.argv[idx + 1])
        # Usa o diretório persistente para salvar o chromedriver
        _set_persistent_cwd()
        remove_trusted_devices.main(workers)
    elif command == "scrape":
        os.chdir(exe_dir)
        scraper.main()
    elif command == "check":
        try:
            # Pré-aquece: usa o diretório persistente para salvar o chromedriver
            _set_persistent_cwd()
            from seleniumbase import SB
            with SB(uc=True, headless=True) as sb:
                pass
            print(json.dumps({"success": True}))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)

if __name__ == '__main__':
    main()
