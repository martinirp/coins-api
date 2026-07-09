# Tibia Coins API & Monitor

API REST e Monitor autônomo em segundo plano para checar recebimentos de Tibia Coins no site oficial do Tibia.com.

Este microserviço automatiza o login (contornando proteções como o Cloudflare Turnstile e autenticação 2FA TOTP), monitora novas transferências de moedas em segundo plano e expõe endpoints HTTP para que outras aplicações validem e consumam esses pagamentos com segurança.

---

## 🛠️ Requisitos de Instalação

### No Windows (Desenvolvimento Local)
1. **Node.js**: Versão 18 ou superior.
2. **Python 3**: Certifique-se de que o Python e o `pip` estão adicionados ao PATH do sistema.
3. **Dependências do Python**:
   ```bash
   pip install seleniumbase pyotp curl-cffi beautifulsoup4
   ```
4. **Dependências do Node**:
   No diretório do projeto, execute:
   ```bash
   npm install
   ```

### No Linux / Termux (PRoot Debian)
1. **Instalar pacotes do sistema**:
   ```bash
   apt update
   apt install -y python3 python3-pip chromium chromium-driver xvfb git nodejs npm
   ```
2. **Instalar dependências do Python**:
   ```bash
   pip3 install pyotp beautifulsoup4 curl-cffi seleniumbase --break-system-packages
   ```
3. **Instalar dependências do Node**:
   ```bash
   npm install
   ```

---

## ⚙️ Configuração (.env)

Crie um arquivo `.env` na raiz do diretório da API com base no arquivo `.env.example`:

```env
PORT=5001
TIBIA_EMAIL=seu_email@tibia.com
TIBIA_PASSWORD=sua_senha
TIBIA_TOTP_KEY=SUA_CHAVE_TOTP_MFA
POLL_INTERVAL_SECONDS=60
```

---

## 🚀 Como Iniciar

### Modo Produção
```bash
npm start
```

### Modo Desenvolvimento
```bash
npm run dev
```

---

## 📡 Endpoints da API

A API escuta por padrão na porta `5001`.

### 1. Listar Histórico
Retorna a lista de recebimentos detectados.

* **URL:** `/api/history`
* **Método:** `GET`
* **Query Params:**
  * `refresh=true` (opcional): Força uma checagem imediata raspando o site do Tibia e atualizando a base local antes de retornar o JSON.
* **Exemplo de Resposta:**
  ```json
  {
    "status": "success",
    "lastCheck": "2026-06-19T22:15:30.000Z",
    "transactions": [
      {
        "id": "89946af6928671e0d970d8630c321679",
        "date": "Jun 19 2026, 21:35:00 CEST",
        "description": "Tamon Dalan gifted to Nora Fylap",
        "character": "Tamon Dalan",
        "amount": 25,
        "used": false,
        "receivedAt": "2026-06-19T22:15:30.000Z"
      }
    ]
  }
  ```

### 2. Verificar Pagamento de Personagem
Verifica se um personagem específico possui algum recebimento pendente maior ou igual ao valor solicitado.

* **URL:** `/api/check-payment`
* **Método:** `GET`
* **Query Params:**
  * `character` (obrigatório): O nome do personagem a buscar.
  * `amount` (obrigatório): Quantidade mínima de moedas (ex: `25`).
* **Comportamento:** Se não encontrar localmente, ele fará uma checagem em tempo real no site do Tibia automaticamente antes de retornar o resultado.
* **Exemplo de Resposta (Sucesso):**
  ```json
  {
    "found": true,
    "payment": {
      "id": "89946af6928671e0d970d8630c321679",
      "date": "Jun 19 2026, 21:35:00 CEST",
      "character": "Tamon Dalan",
      "amount": 25,
      "used": false,
      "receivedAt": "2026-06-19T22:15:30.000Z"
    }
  }
  ```

### 3. Utilizar Pagamento (Evitar Reuso)
Marca uma transação específica como utilizada, vinculando-a a metadados específicos (como a chave UUID ativada). Uma vez utilizada, ela não poderá ser empregada para ativar outra licença.

* **URL:** `/api/use-payment`
* **Método:** `POST`
* **Headers:** `Content-Type: application/json`
* **Corpo (JSON):**
  ```json
  {
    "id": "89946af6928671e0d970d8630c321679",
    "metadata": {
      "uuid": "UUID-DO-CLIENTE-12345",
      "product": "M-Auth License"
    }
  }
  ```
* **Exemplo de Resposta:**
  ```json
  {
    "status": "success",
    "message": "Transação marcada como utilizada com sucesso.",
    "payment": {
      "id": "89946af6928671e0d970d8630c321679",
      "date": "Jun 19 2026, 21:35:00 CEST",
      "character": "Tamon Dalan",
      "amount": 25,
      "used": true,
      "usedAt": "2026-06-19T22:20:00.000Z",
      "usedMetadata": {
        "uuid": "UUID-DO-CLIENTE-12345",
        "product": "M-Auth License"
      }
    }
  }
  ```

### 4. Consultar Status do Sistema
Exibe o estado de integridade da sessão do Tibia e as configurações da API.

* **URL:** `/api/status`
* **Método:** `GET`
* **Exemplo de Resposta:**
  ```json
  {
    "status": "online",
    "sessionValid": true,
    "lastBackgroundCheck": "2026-06-19T22:15:30.000Z",
    "checkingActive": true
  }
  ```

---

## 🔒 Segurança e Resiliência (Bypass do Cloudflare)

* **Sessão Persistente:** Os cookies de sessão válidos são salvos em `session_cookie.txt`. A API usa requisições leves de rede (`curl-cffi` de alta performance) para ler a tabela, o que evita desperdício de memória e detecções indesejadas do WAF.
* **Auto-Recuperação (Self-Healing):** Caso a sessão expire, o servidor inicia automaticamente o script `sb_login.py` de forma oculta (headless) usando o SeleniumBase UC Mode para logar novamente, resolver o Cloudflare Turnstile, pegar um novo token e salvar os novos cookies de sessão sem intervenção humana.
