# Modo offline — design

**Data:** 2026-06-29
**Objetivo:** Fazer a agenda abrir e ser útil **sem internet** (ex.: durante um voo), mostrando os últimos dados conhecidos, e **atualizar sozinha** na próxima vez que houver conexão.

## Contexto

O PWA já tem service worker network-first ([sw.js](../../../sw.js)) que cacheia `index.html`, `manifest.json` e `./`. A casca HTML e o dict `SOBREAVISOS` (hardcoded em [index.html:160](../../../index.html#L160)) **já ficam disponíveis offline**. Mesmo assim, a agenda não abre sem internet.

### Causa raiz — boot acoplado ao script de login do Google

O boot atual ([index.html:738](../../../index.html#L738)) chama `loadGsi()`, que injeta `https://accounts.google.com/gsi/client` ([index.html:266-271](../../../index.html#L266-L271)). **Só no `onload` desse script** é que `initGsi()` roda, verifica o login em cache e chama `showDashboard()` ([index.html:291-298](../../../index.html#L291-L298)).

Sem internet → o script nunca baixa → `onload` nunca dispara → `showDashboard()` nunca é chamado → o dashboard nunca renderiza, apesar dos dados estarem salvos no aparelho. Não há `onerror` no script, então a falha é silenciosa (tela presa no login / em branco).

### Agravante — token expira em ~1h

`saveAuth()` guarda `expires_at = now + expires_in(3600s) − 60s` ([index.html:244-246](../../../index.html#L244-L246)). Num voo, o token quase sempre já expirou e `loadAuth()` retorna `null`. **Conclusão de design:** a decisão de abrir offline NÃO pode depender de token válido — tem que depender de "já logou antes / tem dados salvos". O registro `agenda_auth_v1` permanece no `localStorage` mesmo expirado (`loadAuth` só lê a validade, não apaga), então sua presença serve de sinal de "já logou".

### Agravante — plantões reais nunca são persistidos

`loadData()` busca o Google Calendar ao vivo a cada abertura ([index.html:302-350](../../../index.html#L302-L350)) e descarta o resultado. Offline, `fetchEvents()` lança erro, é capturado ([index.html:350](../../../index.html#L350)) e o app cai na **projeção sintética** — perdendo os plantões reais já conhecidos.

## Decisões tomadas (brainstorming)

- **Dados HVC offline:** mostrar os **últimos plantões reais salvos** (não a projeção). Atualiza ao reconectar.
- **Aviso visual:** faixa **discreta** quando estiver usando dados salvos — ex.: `📡 Offline · dados de 28/06 14h`. Some quando uma atualização online der certo.
- **Abordagem de boot:** offline-first — renderizar primeiro com dados salvos, autenticar/atualizar depois em segundo plano (Abordagem A). Descartadas: (B) cachear o script GSI — não funciona, OAuth precisa de rede e o Google proíbe auto-hospedar; (C) timeout/corrida no load do GSI — pior UX que renderizar na hora.
- **Escopo:** todas as mudanças em `index.html`. `sw.js` já está correto e **não será alterado** (logo, sem bump de `CACHE`).

## Arquitetura

Quatro peças independentes, todas em `index.html`.

### 1. Cache dos plantões reais (`localStorage`)

Nova chave `agenda_hvc_cache_v1` = `{ events: [...], savedAt: <ms epoch> }`, guardando o array bruto `items` do Google Calendar (faithful: a transformação continua num só lugar, dentro de `loadData`).

- Em `fetchEvents()` (ou logo após), no sucesso: salvar `{ events, savedAt: Date.now() }`.
- Volume: ~1 ano, `maxResults=250`, JSON pequeno — bem dentro do limite do `localStorage`.
- Helpers: `saveHvcCache(events)`, `loadHvcCache()` → `{events, savedAt}|null`, `hasHvcCache()`.

### 2. Boot desacoplado

Substituir a chamada `loadGsi()` final por uma decisão imediata + carga do GSI em segundo plano:

```
var hasSession = hasHvcCache() || !!localStorage.getItem(AUTH_KEY);
if (hasSession) {
  accessToken = loadAuth();      // pode ser null (token expirado) — tudo bem
  showDashboard();               // renderiza cache + SOBREAVISOS na hora
} else {
  // permanece na tela de login
}
loadGsiBestEffort();             // segundo plano: login interativo + refresh quando online
```

Mudanças associadas:
- `loadGsi()` ganha `s.onerror` (offline: app já renderizou do cache; ignora).
- `initGsi()` deixa de ser o gatilho do `showDashboard` no caminho de cache; vira **idempotente** — só wira o botão de login e tenta refresh silencioso quando online, sem re-mostrar o dashboard nem piscar spinner se já está renderizado. Guarda contra dupla-init.

### 3. `loadData()` ciente de offline

Reescrever o início de `loadData()` para preferir rede, cair pro cache, e sinalizar estado:

```
loadData(background) {
  // só mostra spinner se NÃO há nada renderizado ainda (evita piscar offline)
  if (!background && !temDadosNaTela) mostra spinner;

  var usouCache = false, lastSync = null;
  if (navigator.onLine && accessToken) {
    try { events = await fetchEvents(); saveHvcCache(events); lastSync = Date.now(); }
    catch { /* cai pro cache abaixo */ }
  }
  if (!events) {
    var c = loadHvcCache();
    if (c) { events = c.events; usouCache = true; lastSync = c.savedAt; }
  }
  // ...transforma events em HVC, projeções, conflitos (lógica atual)...
  offlineState = { stale: usouCache || !navigator.onLine, lastSync: lastSync };
  render();
}
```

`offlineState` é uma variável de módulo lida pelo render.

### 4. Faixa discreta de offline (render)

No topo do `render()` (~[index.html:408](../../../index.html#L408)), antes do banner "HOJE": se `offlineState.stale` (ou `!navigator.onLine`), inserir uma faixa fina com `📡 Offline · dados de {DD/MM HHh}` usando `offlineState.lastSync`. Quando uma atualização online dá certo (`stale=false`), a faixa não é renderizada. CSS novo discreto (cinza/âmbar suave), coerente com `.note`/`.push-prompt`.

### 5. Auto-atualização ao reconectar

```
window.addEventListener('online', function() {
  if (!gsiLoaded) loadGsiBestEffort();   // se o GSI falhou offline, recarrega
  if (accessToken) loadData(true);        // refresh em segundo plano (sem spinner)
  // se token expirado, o refresh silencioso do GSI assume e dispara loadData no callback
});
```

## Edge cases

- **Token expirado + online:** boot renderiza cache; GSI carrega; refresh silencioso (`prompt:''`) obtém token novo → callback chama `loadData` → dados frescos + faixa some.
- **Nunca logou + offline:** sem cache e sem registro de auth → permanece na tela de login (não há como obter HVC; SOBREAVISOS sozinho seria mudança de comportamento maior, fora de escopo).
- **Primeira carga da versão nova:** precisa abrir online uma vez pro novo `index.html` ser cacheado pelo SW (inerente a qualquer correção; network-first cuida disso).
- **`localStorage` cheio/bloqueado (modo privado iOS):** `saveHvcCache` em `try/catch`; falha silenciosa cai no comportamento atual (projeção offline).

## Testes

Não há suite no projeto (PWA estático). Verificação **manual**:

1. Abrir online → dashboard com plantões reais.
2. DevTools → Network → Offline → recarregar → **dashboard abre** com plantões reais salvos + faixa `📡 Offline · dados de …`.
3. Voltar online → após alguns segundos / evento `online`, dados atualizam e a faixa some, **sem recarregar**.
4. `localStorage` limpo + offline → cai na tela de login (esperado).

Opcional: automatizar 1–3 com Playwright (servidor local `python -m http.server`, `context.setOffline(true/false)`).

## Riscos

- **Baixo.** Mudanças isoladas em `index.html`; SW intocado. Pior caso de regressão (cache corrompido / parse falho) cai no comportamento atual via `try/catch`.
- Garantir que o boot não renderize dashboard pra quem nunca logou (checar sinal de sessão corretamente).
- Evitar flash de spinner em refresh de segundo plano (gate `background`/`temDadosNaTela`).
