const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const { exec, execSync } = require('child_process');
const os = require('os');

const app = express();
const PORT = 5001;
const POLL_INTERVAL_SECONDS = 60;
const PYTHON_CMD = os.platform() === 'win32' ? 'python' : 'python3';

app.use(cors());
app.use(express.json());

const PAYMENTS_FILE = path.join(__dirname, 'payments.json');
let lastCheckTime = null;
let isChecking = false;

// Inicializa a base de dados local se não existir
if (!fs.existsSync(PAYMENTS_FILE)) {
  fs.writeFileSync(PAYMENTS_FILE, '[]', 'utf8');
}

// Carregar transações
function loadPayments() {
  try {
    if (fs.existsSync(PAYMENTS_FILE)) {
      return JSON.parse(fs.readFileSync(PAYMENTS_FILE, 'utf8'));
    }
  } catch (err) {
    console.error('[-] Erro ao ler payments.json:', err.message);
  }
  return [];
}

// Salvar transações
function savePayments(payments) {
  try {
    fs.writeFileSync(PAYMENTS_FILE, JSON.stringify(payments, null, 2), 'utf8');
  } catch (err) {
    console.error('[-] Erro ao salvar payments.json:', err.message);
  }
}

// Renovar a sessão usando o SeleniumBase UC Mode
function renewSession() {
  const scriptPath = path.join(__dirname, 'cli.py');
  console.log(`[*] Executando login automatico via Python...`);
  try {
    const stdout = execSync(`${PYTHON_CMD} "${scriptPath}" login`, { cwd: __dirname, encoding: 'utf8' });
    console.log(stdout);
    return stdout.includes('Cookies de sessao salvos com sucesso');
  } catch (err) {
    console.error(`[-] Erro ao executar login via Python: ${err.message}`);
    return false;
  }
}

// Executar scraper de forma assíncrona e atualizar o histórico local
function runScraper() {
  if (isChecking) return Promise.resolve(null);
  isChecking = true;
  
  return new Promise((resolve) => {
    const cookieFile = path.join(__dirname, 'session_cookie.txt');
    
    // Se o cookie de sessão não existir, força o login inicial primeiro
    if (!fs.existsSync(cookieFile)) {
      console.log('[*] Cookie de sessao nao encontrado. Iniciando login primario...');
      const loginOk = renewSession();
      if (!loginOk) {
        isChecking = false;
        return resolve({ error: 'Nao foi possivel iniciar sessao (login falhou).' });
      }
    }

    const scraperPath = path.join(__dirname, 'cli.py');
    console.log(`[*] Buscando dados no site do Tibia via Python...`);
    
    exec(`${PYTHON_CMD} "${scraperPath}" scrape`, { cwd: __dirname }, (error, stdout, stderr) => {
      isChecking = false;
      lastCheckTime = new Date().toISOString();
      
      if (error) {
        console.error(`[-] Erro ao executar scraper via Python: ${error.message}`);
        return resolve({ error: error.message });
      }
      
      try {
        const result = JSON.parse(stdout.trim());
        
        // Se a sessão estiver expirada, tenta fazer login e raspar novamente
        if (result.error === 'session_expired') {
          console.log('[*] A sessao expirou. Iniciando fluxo de renovação automática...');
          const loginOk = renewSession();
          if (loginOk) {
            // Tenta raspar novamente após login bem sucedido
            const retryStdout = execSync(`${PYTHON_CMD} "${scraperPath}" scrape`, { cwd: __dirname });
            const retryResult = JSON.parse(retryStdout.toString().trim());
            if (retryResult.status === 'success') {
              processScraperTransactions(retryResult.transactions);
              return resolve({ status: 'success', transactions: retryResult.transactions });
            }
          }
          return resolve({ error: 'session_expired' });
        }
        
        if (result.status === 'success') {
          processScraperTransactions(result.transactions);
          return resolve({ status: 'success', transactions: result.transactions });
        }
        
        return resolve({ error: result.error || 'Erro desconhecido' });
      } catch (err) {
        console.error(`[-] Erro ao processar saida do scraper: ${err.message}. Saida bruta: ${stdout}`);
        return resolve({ error: `JSON Parse error: ${err.message}` });
      }
    });
  });
}

// Processa as transações do scraper e guarda novos recebimentos
function processScraperTransactions(transactions) {
  if (!transactions || !Array.isArray(transactions)) return;
  
  const payments = loadPayments();
  let updated = false;
  
  // Iterar em ordem cronológica (de trás para frente)
  for (let i = transactions.length - 1; i >= 0; i--) {
    const tx = transactions[i];
    // Apenas armazenamos depósitos/recebimentos no banco de pagamentos
    if (tx.amount <= 0) continue;
    
    const exists = payments.some(p => p.id === tx.id);
    if (!exists) {
      payments.push({
        id: tx.id,
        date: tx.date,
        character: tx.character,
        amount: tx.amount,
        used: false,
        receivedAt: new Date().toISOString()
      });
      updated = true;
      console.log(`[*] [NOVO PAGAMENTO ENCONTRADO] ${tx.amount} TC de '${tx.character}' (Data: ${tx.date})`);
    }
  }
  
  if (updated) {
    savePayments(payments);
  }
}

// ==============================================================================
// ROTAS DA API
// ==============================================================================

// 1. GET /api/history - Retorna o histórico de moedas completo
app.get('/api/history', async (req, res) => {
  const forceRefresh = req.query.refresh === 'true';
  
  if (forceRefresh) {
    console.log('[*] Refresh forcado requisitado na listagem de historico.');
    const checkResult = await runScraper();
    if (checkResult && checkResult.error) {
      return res.status(502).json({ error: 'Erro ao consultar o Tibia em tempo real', details: checkResult.error });
    }
  }
  
  const payments = loadPayments();
  res.json({
    status: 'success',
    lastCheck: lastCheckTime,
    transactions: payments
  });
});

// 2. GET /api/check-payment - Confere se um personagem enviou moedas
app.get('/api/check-payment', async (req, res) => {
  const { character, amount } = req.query;
  
  if (!character || !amount) {
    return res.status(400).json({ error: 'Parâmetros character e amount são obrigatórios.' });
  }
  
  const cleanChar = character.trim().toLowerCase().replace(/\s+/g, ' ');
  const targetAmount = parseInt(amount, 10);
  
  if (isNaN(targetAmount) || targetAmount <= 0) {
    return res.status(400).json({ error: 'O valor do pagamento (amount) deve ser um número positivo.' });
  }
  
  let payments = loadPayments();
  
  // 1. Procura primeiro localmente
  let payment = payments.find(p => 
    p.character.trim().toLowerCase().replace(/\s+/g, ' ') === cleanChar && 
    p.amount >= targetAmount && 
    !p.used
  );
  
  // 2. Se não achar, força o scraper a atualizar o histórico
  if (!payment) {
    console.log(`[*] Pagamento para '${character}' nao encontrado localmente. Fazendo checagem em tempo real...`);
    const checkResult = await runScraper();
    
    if (checkResult && !checkResult.error) {
      payments = loadPayments();
      payment = payments.find(p => 
        p.character.trim().toLowerCase().replace(/\s+/g, ' ') === cleanChar && 
        p.amount >= targetAmount && 
        !p.used
      );
    }
  }
  
  if (payment) {
    return res.json({ found: true, payment });
  }
  
  res.json({ 
    found: false, 
    error: `Nenhum pagamento nao utilizado com valor de pelo menos ${targetAmount} TC foi localizado para o personagem '${character}'.` 
  });
});

// 3. POST /api/use-payment - Marca uma transação como usada
app.post('/api/use-payment', (req, res) => {
  const { id, metadata } = req.body;
  
  if (!id) {
    return res.status(400).json({ error: 'O ID da transação é obrigatório.' });
  }
  
  const payments = loadPayments();
  const paymentIdx = payments.findIndex(p => p.id === id);
  
  if (paymentIdx === -1) {
    return res.status(404).json({ error: 'Transação não encontrada.' });
  }
  
  if (payments[paymentIdx].used) {
    return res.status(409).json({ 
      error: 'Transação já utilizada anteriormente.', 
      usedAt: payments[paymentIdx].usedAt,
      usedMetadata: payments[paymentIdx].usedMetadata
    });
  }
  
  // Marcar como usado e acoplar metadados adicionais (como UUID)
  payments[paymentIdx].used = true;
  payments[paymentIdx].usedAt = new Date().toISOString();
  payments[paymentIdx].usedMetadata = metadata || {};
  
  savePayments(payments);
  console.log(`[+] Transação ${id} marcada como usada. Metadados:`, metadata);
  
  res.json({
    status: 'success',
    message: 'Transação marcada como utilizada com sucesso.',
    payment: payments[paymentIdx]
  });
});

// 4. GET /api/status - Saúde e status da API
app.get('/api/status', (req, res) => {
  const cookieFile = path.join(__dirname, 'session_cookie.txt');
  const sessionExists = fs.existsSync(cookieFile);
  
  res.json({
    status: 'online',
    sessionValid: sessionExists,
    lastBackgroundCheck: lastCheckTime,
    checkingActive: POLL_INTERVAL_SECONDS > 0
  });
});

// 5. POST /api/remove-trusted-devices - Remove todos os Trusted Devices de cada conta
// Body: { "accounts": [{ "name": "...", "email": "...", "password": "...", "totp_secret": "..." }] }
app.post('/api/remove-trusted-devices', (req, res) => {
  const { accounts: accountsList } = req.body;

  if (!accountsList || !Array.isArray(accountsList) || accountsList.length === 0) {
    return res.status(400).json({ error: 'Campo "accounts" é obrigatório e deve ser uma lista não vazia.' });
  }

  // Filtra apenas contas com email e senha preenchidos
  const validAccounts = accountsList.filter(a => a.email && a.password);
  if (validAccounts.length === 0) {
    return res.status(400).json({ error: 'Nenhuma conta válida (com email e senha) encontrada na lista.' });
  }

  const scriptPath = path.join(__dirname, 'remove_trusted_devices.py');
  console.log(`[*] Iniciando remoção de Trusted Devices para ${validAccounts.length} conta(s) via Python...`);

  const inputJson = JSON.stringify(validAccounts);

  // Workers = valor do campo max_workers enviado pelo cliente (padrão 3)
  const maxWorkers = String(req.body.max_workers || 3);

  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Transfer-Encoding', 'chunked');

  const child = require('child_process').spawn(PYTHON_CMD, [scriptPath, '--workers', maxWorkers], {
    cwd: __dirname,
    stdio: ['pipe', 'pipe', 'pipe']
  });

  // Envia as contas via stdin
  child.stdin.write(inputJson);
  child.stdin.end();

  let stdoutBuffer = '';
  let stderrBuffer = '';

  child.stdout.on('data', (data) => {
    const text = data.toString();
    stdoutBuffer += text;
    // Loga no servidor em tempo real
    process.stdout.write(text);
  });

  child.stderr.on('data', (data) => {
    const text = data.toString();
    stderrBuffer += text;
    process.stderr.write(text);
  });

  child.on('close', (code) => {
    console.log(`[*] remove_trusted_devices.py finalizado com código: ${code}`);

    // Tenta extrair o JSON de resultado da última linha do stdout
    const lines = stdoutBuffer.trim().split('\n');
    let result = null;
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        result = JSON.parse(lines[i].trim());
        break;
      } catch (_) {}
    }

    if (result) {
      return res.json(result);
    }

    // Se não encontrou JSON, retorna o log bruto
    res.json({
      status: code === 0 ? 'finished' : 'error',
      exitCode: code,
      log: stdoutBuffer,
      stderr: stderrBuffer
    });
  });

  child.on('error', (err) => {
    console.error(`[-] Erro ao executar remove_trusted_devices.py: ${err.message}`);
    if (!res.headersSent) {
      res.status(500).json({ error: err.message });
    }
  });
});

// ==============================================================================
// INICIALIZAÇÃO E LOOP DE MONITORAMENTO
// ==============================================================================

app.listen(PORT, '0.0.0.0', () => {
  console.log(`==================================================`);
  console.log(`🚀 Tibia Coins API is running on port ${PORT}`);
  console.log(`🌐 Acesse localmente: http://localhost:${PORT}`);
  console.log(`==================================================`);
  
  // Iniciar loop de checagem em segundo plano se configurado
  if (POLL_INTERVAL_SECONDS > 0) {
    console.log(`[*] Escuta ativa de segundo plano iniciada (A cada ${POLL_INTERVAL_SECONDS} segundos)`);
    
    // Executa uma vez na inicialização
    runScraper().catch(() => {});
    
    // Configura o intervalo
    setInterval(() => {
      console.log(`\n[*] [${new Date().toLocaleTimeString()}] Executando checagem periodica de historico...`);
      runScraper().catch(() => {});
    }, POLL_INTERVAL_SECONDS * 1000);
  } else {
    console.log(`[*] Escuta de segundo plano desativada. As checagens ocorrerão apenas sob demanda.`);
    
    // Keep event loop alive (para rodar estável em ambientes PRoot/Termux)
    setInterval(() => {}, 60000);
  }
});
