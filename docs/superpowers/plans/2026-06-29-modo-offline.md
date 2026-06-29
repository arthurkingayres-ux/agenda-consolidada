# Modo offline — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer a agenda abrir e mostrar os últimos plantões conhecidos **sem internet**, atualizando sozinha quando a conexão voltar.

**Architecture:** Boot offline-first — em vez de esperar o script de login do Google baixar, o app decide na hora se já tem sessão (cache de plantões ou registro de auth) e renderiza imediatamente do `localStorage`; o GSI carrega em segundo plano e dispara um refresh quando há rede. Os plantões reais do Google Calendar passam a ser persistidos em `localStorage` (`agenda_hvc_cache_v1`) para sobreviver offline. Uma faixa discreta avisa quando os dados são salvos/antigos.

**Tech Stack:** HTML + CSS + JS vanilla inline (arquivo único `index.html`), `localStorage`, Google Identity Services (GSI), Service Worker (network-first, **não alterado**).

## Global Constraints

Cada uma destas regras vale para **todas** as tarefas abaixo (valores copiados do spec e do CLAUDE.md):

- **Escopo de arquivos:** todas as mudanças são em `index.html`. `sw.js` **não** é tocado → **sem bump de `CACHE`**.
- **Dict `SOBREAVISOS`** (em [index.html:160](../../../index.html#L160)): **nunca editar à mão**. Não encostar nele.
- **Linguagem:** PT-BR em commits, comentários e UI.
- **Commits:** prefixo `feat:` / `fix:` / `chore:`. Toda mensagem de commit termina com a linha:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **`localStorage` sempre em `try/catch`** (modo privado do iOS pode bloquear; falha tem que ser silenciosa e cair no comportamento atual).
- **Testes:** o projeto não tem suite automatizada. Verificação é por **console do navegador** (snippets concretos abaixo) e **teste manual offline** via DevTools → Network → Offline. Para servir localmente: `python -m http.server 8000` na raiz do repo, depois `http://localhost:8000` (o SW precisa de HTTP, não `file://`).
- **Naming travado** (usado entre tarefas):
  - Chave de cache: `HVC_CACHE_KEY = 'agenda_hvc_cache_v1'`; valor `{ events: <array items do Calendar>, savedAt: <ms epoch> }`.
  - Helpers: `saveHvcCache(events)`, `loadHvcCache() → {events, savedAt} | null`, `hasHvcCache() → bool`.
  - Estado de módulo: `offlineState = { stale: <bool>, lastSync: <ms|null> }`, `hasRendered = <bool>`, `gsiLoaded = <bool>`, `gsiInited = <bool>`.
  - `loadData(background)` — `background` truthy = refresh sem spinner.
  - `fmtSync(ms) → 'DD/MM HHh'`.
  - Boot interativo: `loadGsiBestEffort()` (substitui a antiga `loadGsi()`).

---

## File Structure

Único arquivo: `index.html`. As peças, por região:

| Região (linhas atuais) | Responsabilidade | Tarefa |
|---|---|---|
| `<style>` ~[L115-126](../../../index.html#L115-L126) | CSS da faixa offline (`.offline-bar`) | 3 |
| Estado de módulo ~[L234-242](../../../index.html#L234-L242) | Novas vars `offlineState`, `hasRendered`, `gsiLoaded`, `gsiInited`, `HVC_CACHE_KEY` | 1, 4 |
| Auth helpers ~[L244-257](../../../index.html#L244-L257) | Helpers de cache HVC, ao lado dos de auth | 1 |
| GSI ~[L266-299](../../../index.html#L266-L299) | `loadGsiBestEffort()` + `initGsi()` idempotente | 4 |
| `loadData()` ~[L318-392](../../../index.html#L318-L392) | Preferir rede → cair pro cache → `offlineState` | 2 |
| `render()` ~[L402-487](../../../index.html#L402-L487) | Faixa offline + `fmtSync` + `hasRendered=true` | 3 |
| Boot final [L738](../../../index.html#L738) | IIFE offline-first + listener `online` | 4, 5 |

---

## Task 1: Cache HVC + estado de módulo

Fundação: novas variáveis de estado e os helpers de leitura/escrita do cache de plantões no `localStorage`. Nada visível ainda; verificável pelo console.

**Files:**
- Modify: `index.html` (estado de módulo após [L242](../../../index.html#L242); helpers após [L257](../../../index.html#L257))

**Interfaces:**
- Consumes: nada (usa `localStorage` nativo).
- Produces (usados pelas tarefas 2, 4 e 5):
  - `var HVC_CACHE_KEY = 'agenda_hvc_cache_v1';`
  - `var offlineState = { stale: false, lastSync: null };`
  - `var hasRendered = false;`
  - `saveHvcCache(events)` → void (grava `{events, savedAt: Date.now()}`)
  - `loadHvcCache()` → `{events, savedAt}` ou `null`
  - `hasHvcCache()` → `bool`

- [ ] **Step 1: Adicionar as variáveis de estado de módulo**

Localizar (linhas [240-242](../../../index.html#L240-L242)):

```js
var accessToken = null;
var AUTH_KEY = 'agenda_auth_v1';
var tokenClient = null;
```

Substituir por:

```js
var accessToken = null;
var AUTH_KEY = 'agenda_auth_v1';
var HVC_CACHE_KEY = 'agenda_hvc_cache_v1';
var tokenClient = null;
var offlineState = { stale: false, lastSync: null };
var hasRendered = false;
```

- [ ] **Step 2: Adicionar os helpers de cache HVC**

Localizar (linha [257](../../../index.html#L257)):

```js
function clearAuth() { try { localStorage.removeItem(AUTH_KEY); } catch(e) {} }
```

Inserir **logo depois** dessa linha:

```js
// ---- Cache dos plantões reais (sobrevive offline) ----
function saveHvcCache(events) {
  try { localStorage.setItem(HVC_CACHE_KEY, JSON.stringify({ events: events, savedAt: Date.now() })); } catch(e) {}
}
function loadHvcCache() {
  try {
    var raw = localStorage.getItem(HVC_CACHE_KEY);
    if (!raw) return null;
    var data = JSON.parse(raw);
    if (data && data.events) return data;
  } catch(e) {}
  return null;
}
function hasHvcCache() {
  try { return !!localStorage.getItem(HVC_CACHE_KEY); } catch(e) { return false; }
}
```

- [ ] **Step 3: Verificar no console**

Servir o site (`python -m http.server 8000`), abrir `http://localhost:8000`, abrir DevTools → Console e rodar:

```js
saveHvcCache([{ id: 'teste', start: { dateTime: '2026-07-01T19:00:00-03:00' } }]);
loadHvcCache();        // → { events: [ {id:'teste',...} ], savedAt: <número> }
hasHvcCache();         // → true
localStorage.removeItem('agenda_hvc_cache_v1');
hasHvcCache();         // → false
```

Esperado: exatamente os retornos comentados acima, sem exceção.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(offline): helpers de cache HVC e estado de módulo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `loadData()` ciente de offline

Reescreve `loadData()` para: preferir a rede quando online+autenticado, persistir o resultado no cache, cair pro cache quando offline/erro, e publicar `offlineState`. Também reseta os acumuladores no início (agora `loadData` pode rodar mais de uma vez — refresh ao reconectar) e ganha o parâmetro `background` para refresh sem spinner.

**Files:**
- Modify: `index.html` — `loadData()` [L318-392](../../../index.html#L318-L392)

**Interfaces:**
- Consumes (da Task 1): `saveHvcCache`, `loadHvcCache`, `offlineState`, `hasRendered`. Também usa `fetchEvents()` (existente, [L302-316](../../../index.html#L302-L316)) e `render()` (existente).
- Produces (usado pelas tarefas 3 e 5): `loadData(background)` com `background` truthy = sem spinner; popula `offlineState = { stale, lastSync }` antes de cada `render()`.

- [ ] **Step 1: Substituir o cabeçalho + bloco de fetch de `loadData`**

Localizar (linhas [318-350](../../../index.html#L318-L350)):

```js
async function loadData() {
  var dash = document.getElementById('dashboard');
  dash.innerHTML = '<div class="loading"><div class="spinner"></div><br>Carregando Pega Plantão...</div>';

  try {
    var events = await fetchEvents();
    events.forEach(function(ev) {
      if (!ev.start || !ev.start.dateTime) return;
      var st = new Date(ev.start.dateTime);
      var en = new Date(ev.end.dateTime);
      var sH = st.getHours(), eH = en.getHours();
      var w = (en.getTime() - st.getTime()) / (1000 * 60 * 60 * 12);
      var key = dk(st.getFullYear(), st.getMonth()+1, st.getDate());
      var ymK = st.getFullYear() + '-' + pad2(st.getMonth()+1);
      realMonths[ymK] = true;
      totalReal++;
      var label = 'HVC';
      if (sH >= 19 || sH < 7) label = 'HVC Noturno';
      else if (sH >= 7 && eH <= 13) label = 'HVC Diurno';
      else if (sH >= 13 && eH <= 19) label = 'HVC Tarde';
      else label = 'HVC Tarde+Noturno';
      var hrs = pad2(sH) + 'h-' + pad2(eH) + 'h';
      if (HVC[key]) {
        HVC[key].label = 'HVC (múltiplos)';
        HVC[key].eventCount = (HVC[key].eventCount || 1) + 1;
        HVC[key].weight = (HVC[key].weight || 0) + w;
        var eS = parseInt(HVC[key].hours.split('h-')[0]);
        HVC[key].hours = pad2(Math.min(eS, sH)) + 'h-' + pad2(eH) + 'h';
      } else {
        HVC[key] = { label: label, hours: hrs, source: 'real', eventCount: 1, weight: w };
      }
    });
  } catch(e) { /* continue with projections */ }
```

Substituir por:

```js
async function loadData(background) {
  var dash = document.getElementById('dashboard');
  // Spinner só na primeira pintura; refresh em 2º plano não pisca a tela.
  if (!background && !hasRendered) {
    dash.innerHTML = '<div class="loading"><div class="spinner"></div><br>Carregando Pega Plantão...</div>';
  }

  // loadData pode rodar mais de uma vez (refresh ao reconectar): zera acumuladores.
  HVC = {}; realMonths = {}; totalReal = 0;

  var events = null, usouCache = false, lastSync = null;

  // 1) Tenta a rede quando há conexão e token.
  if (navigator.onLine && accessToken) {
    try {
      events = await fetchEvents();
      saveHvcCache(events);
      lastSync = Date.now();
    } catch(e) { events = null; }
  }

  // 2) Sem rede / sem token / falhou → usa os últimos plantões salvos.
  if (!events) {
    var cached = loadHvcCache();
    if (cached) { events = cached.events; usouCache = true; lastSync = cached.savedAt; }
  }

  // 3) Transforma os eventos (reais ou do cache) no dict HVC.
  if (events) {
    events.forEach(function(ev) {
      if (!ev.start || !ev.start.dateTime) return;
      var st = new Date(ev.start.dateTime);
      var en = new Date(ev.end.dateTime);
      var sH = st.getHours(), eH = en.getHours();
      var w = (en.getTime() - st.getTime()) / (1000 * 60 * 60 * 12);
      var key = dk(st.getFullYear(), st.getMonth()+1, st.getDate());
      var ymK = st.getFullYear() + '-' + pad2(st.getMonth()+1);
      realMonths[ymK] = true;
      totalReal++;
      var label = 'HVC';
      if (sH >= 19 || sH < 7) label = 'HVC Noturno';
      else if (sH >= 7 && eH <= 13) label = 'HVC Diurno';
      else if (sH >= 13 && eH <= 19) label = 'HVC Tarde';
      else label = 'HVC Tarde+Noturno';
      var hrs = pad2(sH) + 'h-' + pad2(eH) + 'h';
      if (HVC[key]) {
        HVC[key].label = 'HVC (múltiplos)';
        HVC[key].eventCount = (HVC[key].eventCount || 1) + 1;
        HVC[key].weight = (HVC[key].weight || 0) + w;
        var eS = parseInt(HVC[key].hours.split('h-')[0]);
        HVC[key].hours = pad2(Math.min(eS, sH)) + 'h-' + pad2(eH) + 'h';
      } else {
        HVC[key] = { label: label, hours: hrs, source: 'real', eventCount: 1, weight: w };
      }
    });
  }
```

> Nota: a única diferença dentro do `forEach` é estar agora dentro de `if (events) { ... }` em vez de `try { ... } catch`. A lógica de classificação/peso é idêntica.

- [ ] **Step 2: Publicar `offlineState` imediatamente antes do `render()`**

Localizar (linha [385](../../../index.html#L385), após o bloco de conflitos):

```js
  render();
```

Substituir por:

```js
  offlineState = { stale: usouCache || !navigator.onLine, lastSync: lastSync };
  render();
```

> Não confundir com o `render()` que está dentro de `pushStep`/`pushFail` (esses ficam intactos). É o `render()` no fim de `loadData`, logo depois do loop de `// Conflicts`.

- [ ] **Step 3: Verificar caminho online (rede)**

Servir, abrir `http://localhost:8000`, logar no Google normalmente. No Console:

```js
loadHvcCache().events.length;   // → > 0 (plantões reais foram persistidos)
offlineState;                   // → { stale: false, lastSync: <número recente> }
```

Esperado: `stale: false` quando carregou da rede com sucesso, e o cache foi gravado.

- [ ] **Step 4: Verificar caminho cache (offline)**

Com o cache já populado pelo Step 3: DevTools → Network → **Offline**. No Console:

```js
await loadData(true);           // refresh em 2º plano, sem spinner
totalReal;                      // → > 0 (plantões vieram do cache, não da projeção)
offlineState.stale;             // → true
```

Esperado: `totalReal > 0` (dados reais do cache, não projeção sintética) e `offlineState.stale === true`. Voltar Network para **No throttling** ao final.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(offline): loadData prefere rede, cai pro cache e publica offlineState

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Faixa discreta de offline no `render()`

Faixa fina no topo do dashboard quando os dados são salvos/antigos, com a data do último sync. Some quando um refresh online dá certo (`offlineState.stale === false`).

**Files:**
- Modify: `index.html` — CSS [L126](../../../index.html#L126); `render()` [L403](../../../index.html#L403) e [L487](../../../index.html#L487); novo helper `fmtSync`

**Interfaces:**
- Consumes (da Task 1/2): `offlineState`, `hasRendered`, `pad2` (existente).
- Produces: `fmtSync(ms)`; seta `hasRendered = true` ao fim de cada `render()`.

- [ ] **Step 1: Adicionar o CSS da faixa**

Localizar (linha [126](../../../index.html#L126)):

```css
.push-prompt.denied { background: #FEE2E2; border-color: #DC2626; color: #991B1B; }
```

Inserir **logo depois**:

```css
.offline-bar { font-size: 11px; color: #92400E; background: #FEF3C7; border: 1px solid #FCD34D; border-radius: 8px; padding: 6px 12px; margin-bottom: 10px; text-align: center; }
```

- [ ] **Step 2: Adicionar o helper `fmtSync`**

Localizar a função `phr` (linha [394](../../../index.html#L394)):

```js
function phr(h) {
```

Inserir **logo antes** dela:

```js
function fmtSync(ms) {
  var d = new Date(ms);
  return pad2(d.getDate()) + '/' + pad2(d.getMonth()+1) + ' ' + pad2(d.getHours()) + 'h';
}
```

- [ ] **Step 3: Renderizar a faixa no topo do dashboard**

Localizar o início de `render()` (linhas [402-403](../../../index.html#L402-L403)):

```js
function render() {
  var h = '';
```

Substituir por:

```js
function render() {
  var h = '';

  // Faixa discreta: dados salvos/antigos (some quando um refresh online dá certo)
  if (offlineState.stale) {
    var syncTxt = offlineState.lastSync ? ' · dados de ' + fmtSync(offlineState.lastSync) : '';
    h += '<div class="offline-bar">📡 Offline' + syncTxt + '</div>';
  }
```

- [ ] **Step 4: Marcar `hasRendered` ao fim de `render()`**

Localizar (linha [487](../../../index.html#L487)):

```js
  document.getElementById('dashboard').innerHTML = h;
```

Substituir por:

```js
  document.getElementById('dashboard').innerHTML = h;
  hasRendered = true;
```

> `render()` tem mais conteúdo depois da linha 487 (handlers de clique etc.); manter tudo isso. Só acrescentar a linha `hasRendered = true;` logo após a atribuição do `innerHTML`.

- [ ] **Step 5: Verificar a faixa**

Servir, logar, popular cache. DevTools → Network → **Offline**. No Console:

```js
await loadData(true);
document.querySelector('.offline-bar').textContent;
// → "📡 Offline · dados de DD/MM HHh"
```

Voltar online e:

```js
await loadData(true);
document.querySelector('.offline-bar');   // → null (faixa sumiu)
```

Esperado: faixa presente com o texto offline; ausente após refresh online bem-sucedido. Voltar Network para **No throttling**.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(offline): faixa discreta de aviso quando usa dados salvos

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Boot offline-first (desacoplar do GSI)

O coração da correção: o app deixa de esperar o script do Google. Decide na hora se há sessão (cache HVC ou registro de auth) e renderiza do cache imediatamente; o GSI carrega em segundo plano e dispara o refresh quando há rede. `initGsi` vira idempotente e o script ganha `onerror`.

**Files:**
- Modify: `index.html` — `loadGsi`→`loadGsiBestEffort` [L266-271](../../../index.html#L266-L271); `initGsi` [L273-299](../../../index.html#L273-L299); boot final [L738](../../../index.html#L738)

**Interfaces:**
- Consumes (das tarefas 1/2): `hasHvcCache`, `loadAuth` (existente), `showDashboard` (existente, chama `loadData()`), `loadData`.
- Produces (usado pela Task 5): `loadGsiBestEffort()`, flags `gsiLoaded`, `gsiInited`, `tokenClient` (já existente).

- [ ] **Step 1: Substituir `loadGsi` por `loadGsiBestEffort`**

Localizar (linhas [265-271](../../../index.html#L265-L271)):

```js
// ============ GOOGLE AUTH ============
function loadGsi() {
  var s = document.createElement('script');
  s.src = 'https://accounts.google.com/gsi/client';
  s.onload = function() { initGsi(); };
  document.head.appendChild(s);
}
```

Substituir por:

```js
// ============ GOOGLE AUTH ============
var gsiLoaded = false;
var gsiInited = false;

function loadGsiBestEffort() {
  if (gsiLoaded || document.getElementById('gsi-script')) return;
  var s = document.createElement('script');
  s.id = 'gsi-script';
  s.src = 'https://accounts.google.com/gsi/client';
  s.onload = function() { gsiLoaded = true; initGsi(); };
  // Offline: o app já renderizou do cache; tentamos de novo no evento 'online'.
  s.onerror = function() { var el = document.getElementById('gsi-script'); if (el) el.remove(); };
  document.head.appendChild(s);
}
```

> `onerror` remove o `<script>` falho para que `loadGsiBestEffort` possa recriá-lo quando a conexão voltar (a guarda checa `getElementById('gsi-script')`).

- [ ] **Step 2: Tornar `initGsi` idempotente e remover o gatilho de showDashboard por cache**

Localizar (linhas [273-299](../../../index.html#L273-L299)):

```js
function initGsi() {
  tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,
    scope: SCOPES,
    callback: function(resp) {
      if (resp.access_token) {
        accessToken = resp.access_token;
        saveAuth(resp.access_token, resp.expires_in);
        showDashboard();
      }
    },
    error_callback: function() { /* silent failures stay on login screen */ }
  });

  document.getElementById('login-btn').addEventListener('click', function() {
    tokenClient.requestAccessToken({ prompt: 'consent' });
  });

  // Try silent auth: cached token → silent refresh → show login button
  var cached = loadAuth();
  if (cached) {
    accessToken = cached;
    showDashboard();
  } else {
    tokenClient.requestAccessToken({ prompt: '' });
  }
}
```

Substituir por:

```js
function initGsi() {
  if (gsiInited) return;   // idempotente: 'online' pode recarregar o GSI
  gsiInited = true;

  tokenClient = google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,
    scope: SCOPES,
    callback: function(resp) {
      if (resp.access_token) {
        accessToken = resp.access_token;
        saveAuth(resp.access_token, resp.expires_in);
        showDashboard();   // garante dashboard visível + loadData() com token novo
      }
    },
    error_callback: function() { /* falha silenciosa: mantém o estado atual */ }
  });

  document.getElementById('login-btn').addEventListener('click', function() {
    tokenClient.requestAccessToken({ prompt: 'consent' });
  });

  // O boot já decidiu o que renderizar. Aqui só buscamos token quando não há
  // um válido em cache (refresh silencioso precisa de rede).
  if (!loadAuth()) {
    tokenClient.requestAccessToken({ prompt: '' });
  }
}
```

- [ ] **Step 3: Substituir a chamada de boot final**

Localizar (linha [738](../../../index.html#L738)):

```js
loadGsi();
```

Substituir por:

```js
// Boot offline-first: renderiza do cache na hora; GSI carrega em 2º plano.
(function boot() {
  var hasSession = hasHvcCache() || !!localStorage.getItem(AUTH_KEY);
  if (hasSession) {
    accessToken = loadAuth();   // pode ser null (token expirado) — tudo bem
    showDashboard();            // renderiza cache + SOBREAVISOS imediatamente
  }
  loadGsiBestEffort();          // login interativo + refresh silencioso quando online
})();
```

- [ ] **Step 4: Verificar boot offline (o cenário do voo)**

Servir, logar online ao menos uma vez (popula cache + `agenda_auth_v1`). Depois:

1. DevTools → Application → Local Storage: confirmar que existem `agenda_hvc_cache_v1` e `agenda_auth_v1`.
2. DevTools → Network → **Offline**.
3. **Recarregar a página** (F5).

Esperado: o **dashboard abre** com os plantões reais salvos (não fica preso no login nem em branco) e a faixa `📡 Offline · dados de …` aparece no topo. No Console: `document.getElementById('dashboard').style.display` → `"block"`.

- [ ] **Step 5: Verificar que quem nunca logou continua no login (offline)**

DevTools → Application → Local Storage → limpar tudo (`agenda_hvc_cache_v1` e `agenda_auth_v1`). Manter Network **Offline**. Recarregar.

Esperado: permanece na **tela de login** (`#login-screen` visível, `#dashboard` oculto) — não há como obter HVC sem sessão. No Console: `document.getElementById('dashboard').style.display` → `"none"` (ou vazio). Voltar Network para **No throttling**.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "fix(offline): boot offline-first desacoplado do script de login do Google

Renderiza do cache imediatamente em vez de esperar o GSI baixar; o GSI
carrega em 2º plano e atualiza quando há rede. Corrige a agenda não abrir
sem internet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Auto-atualização ao reconectar

Quando a conexão volta, recarrega o GSI se ele falhou offline e dispara um refresh em segundo plano; se o token expirou, pede um silencioso.

**Files:**
- Modify: `index.html` — boot final (logo antes da IIFE `boot`, ~[L738](../../../index.html#L738))

**Interfaces:**
- Consumes (da Task 4): `gsiLoaded`, `gsiInited`, `loadGsiBestEffort`, `tokenClient`, `accessToken`, `loadData`.
- Produces: nada (efeito colateral — atualização automática).

- [ ] **Step 1: Adicionar o listener `online`**

Localizar o comentário e a IIFE de boot adicionados na Task 4:

```js
// Boot offline-first: renderiza do cache na hora; GSI carrega em 2º plano.
(function boot() {
```

Inserir **logo antes** dessa linha de comentário:

```js
// Reconectou: recarrega o GSI se falhou offline e atualiza os dados.
window.addEventListener('online', function() {
  if (!gsiLoaded) loadGsiBestEffort();
  if (accessToken) {
    loadData(true);                                  // refresh em 2º plano
  } else if (gsiInited && tokenClient) {
    tokenClient.requestAccessToken({ prompt: '' });  // token expirado → callback dispara loadData
  }
  // Se o GSI ainda não inicializou, seu onload→initGsi cuida do refresh silencioso.
});

```

- [ ] **Step 2: Verificar auto-update ao reconectar**

Servir, logar, popular cache. DevTools → Network → **Offline** → recarregar (dashboard abre do cache, faixa offline visível). Então, **sem recarregar a página**, DevTools → Network → **No throttling** (volta online).

Esperado: em poucos segundos os dados atualizam e a faixa `📡 Offline …` **some sozinha** (sem reload). No Console, logo após voltar online:

```js
// aguardar ~2-3s e então:
offlineState.stale;                       // → false
document.querySelector('.offline-bar');   // → null
```

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat(offline): atualiza dados automaticamente ao reconectar

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Verificação final (E2E manual)

Sequência completa que reproduz o cenário do voo (do spec, seção Testes):

1. **Online → reload:** dashboard com plantões reais (badge `✓`), sem faixa offline.
2. **Network Offline → reload:** dashboard **abre** com plantões reais salvos + faixa `📡 Offline · dados de …`. (Era aqui que travava antes.)
3. **Network online (sem reload):** após alguns segundos / evento `online`, dados atualizam e a faixa some, **sem recarregar**.
4. **Local Storage limpo + Offline → reload:** cai na tela de login (esperado).
5. **Confirmar `sw.js` intocado:** `git diff --name-only main` na branch deve listar **apenas** `index.html` (+ docs do plano). Nada de `sw.js` → nenhum bump de `CACHE` necessário.

> Lembrete (do spec, edge case): a primeira vez que a versão nova é baixada precisa de **uma** abertura online para o SW cachear o novo `index.html`. Inerente a qualquer correção; o network-first cuida disso a partir daí.

---

## Self-Review (cobertura do spec)

- **Causa raiz (boot acoplado ao GSI)** → Task 4 (boot IIFE + `loadGsiBestEffort`). ✓
- **Peça 1: cache `agenda_hvc_cache_v1`** → Task 1 (helpers) + Task 2 (grava no sucesso). ✓
- **Peça 2: boot desacoplado** → Task 4 (IIFE, `onerror`, `initGsi` idempotente). ✓
- **Peça 3: loadData ciente de offline** → Task 2 (preferir rede → cache, `background`, `offlineState`, reset de acumuladores). ✓
- **Peça 4: faixa discreta** → Task 3 (CSS `.offline-bar` + render + `fmtSync`). ✓
- **Peça 5: auto-update no `online`** → Task 5. ✓
- **Edge — token expirado + online:** boot renderiza cache; `initGsi` faz `requestAccessToken({prompt:''})` quando `!loadAuth()`; callback → `showDashboard`→`loadData` com token novo. ✓
- **Edge — nunca logou + offline:** Task 4 Step 5 confirma que fica no login. ✓
- **Edge — `localStorage` bloqueado (iOS privado):** todos os acessos em `try/catch` (Task 1). ✓
- **Risco — flash de spinner em refresh:** gate `!background && !hasRendered` (Task 2/3). ✓
- **Risco — dados duplicados em re-render:** reset `HVC/realMonths/totalReal` no topo de `loadData` (Task 2). ✓
- **Naming consistente:** `loadData(background)`, `offlineState{stale,lastSync}`, `fmtSync`, `loadGsiBestEffort`, `gsiLoaded`/`gsiInited`, `HVC_CACHE_KEY` — usados com os mesmos nomes em todas as tarefas. ✓
- **sw.js intocado / sem bump de CACHE** → verificado no E2E passo 5. ✓
