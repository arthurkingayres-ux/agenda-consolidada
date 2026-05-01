# Push Notifications HVC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Web Push notifications to the PWA (iOS iPhone) that alert 24h e 1h antes de cada plantão HVC.

**Architecture:** PWA registra Web Push subscription no iOS e envia timestamps dos plantões HVC ao Cloudflare Worker. Worker armazena subscription + eventos em KV e tem cron trigger horário que verifica janelas de 24h/1h e envia notificações. Implementação de Web Push usa Web Crypto API pura (sem npm) para poder ser colada diretamente no editor do Cloudflare dashboard via Playwright MCP.

**Tech Stack:** Web Push (RFC 8291 + RFC 8292), Web Crypto API, Cloudflare Workers, Cloudflare KV, Playwright MCP para setup no dashboard.

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `sw.js` | Modificar | Adicionar handler do evento `push`; bump cache v2 |
| `index.html` | Modificar | Adicionar `registerNotifications()`, constantes VAPID/WORKER_URL, wiring em `loadData()` |
| `notifications-worker/src/index.js` | Criar | Cloudflare Worker: rota POST /subscribe + cron handler com Web Push |

---

## Task 1: Gerar chaves VAPID

**Files:** nenhum (geração de chaves, resultado salvo para tarefas seguintes)

- [ ] **Step 1: Gerar par de chaves**

Requer Node.js. Rodar no terminal:

```bash
npx web-push generate-vapid-keys
```

Saída esperada:
```
=======================================

Public Key:
BExemploChavePublica64Caracteres...

Private Key:
ExemploChavePrivada43Caracteres...

=======================================
```

- [ ] **Step 2: Salvar as chaves**

Manter ambas em um bloco de texto aberto. Serão usadas na Task 4 (index.html) e Task 5 (Cloudflare). **Nunca commitar a chave privada.**

---

## Task 2: Atualizar sw.js — handler push

**Files:**
- Modify: `sw.js`

- [ ] **Step 1: Substituir sw.js inteiro**

Conteúdo completo do novo `sw.js`:

```javascript
var CACHE = 'agenda-arthur-v2';
var URLS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', function(e) {
  e.waitUntil(caches.open(CACHE).then(function(c) { return c.addAll(URLS); }));
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE; }).map(function(n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  if (e.request.url.includes('googleapis.com') || e.request.url.includes('accounts.google.com')) {
    return;
  }
  e.respondWith(
    caches.match(e.request).then(function(r) { return r || fetch(e.request); })
  );
});

self.addEventListener('push', function(e) {
  var data = {};
  try { data = e.data ? e.data.json() : {}; } catch(err) {}
  e.waitUntil(
    self.registration.showNotification(data.title || 'Plantão HVC', {
      body: data.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      requireInteraction: false
    })
  );
});
```

- [ ] **Step 2: Commit**

```bash
git add sw.js
git commit -m "feat: add push event handler to service worker, bump cache v2"
```

---

## Task 3: Criar notifications-worker/src/index.js

**Files:**
- Create: `notifications-worker/src/index.js`

Este arquivo será versionado no repo e também colado no editor do Cloudflare dashboard (Task 5).

- [ ] **Step 1: Criar o arquivo**

Conteúdo completo de `notifications-worker/src/index.js`:

```javascript
// Web Push via Web Crypto API — sem dependências npm
// RFC 8291 (message encryption) + RFC 8292 (VAPID)

function b64u(buf) {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let str = '';
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function fromb64u(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  s += '='.repeat((4 - s.length % 4) % 4);
  return Uint8Array.from(atob(s), c => c.charCodeAt(0));
}

function concat(...arrays) {
  const total = arrays.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(total);
  let i = 0;
  for (const a of arrays) { out.set(a, i); i += a.length; }
  return out;
}

async function hmac256(key, data) {
  const k = await crypto.subtle.importKey('raw', key, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', k, data));
}

async function hkdfExpand(prk, info, len) {
  return (await hmac256(prk, concat(info, new Uint8Array([1])))).slice(0, len);
}

async function sendPush(subscription, payloadObj, vapidPublicKey, vapidPrivateKey, vapidSubject) {
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payloadObj));

  // ── Encrypt payload (RFC 8291 + RFC 8188 aes128gcm) ──────────────────────
  const authSecret    = fromb64u(subscription.keys.auth);
  const receiverPubRaw = fromb64u(subscription.keys.p256dh);

  const receiverPub = await crypto.subtle.importKey(
    'raw', receiverPubRaw, { name: 'ECDH', namedCurve: 'P-256' }, true, []
  );
  const senderPair = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']
  );
  const senderPubRaw = new Uint8Array(await crypto.subtle.exportKey('raw', senderPair.publicKey));

  const ecdhSecret = new Uint8Array(await crypto.subtle.deriveBits(
    { name: 'ECDH', public: receiverPub }, senderPair.privateKey, 256
  ));

  // PRK_key = HMAC(auth_secret, ecdh_secret)
  const prkKey = await hmac256(authSecret, ecdhSecret);

  // IKM = HKDF-Expand(PRK_key, "WebPush: info\0" || receiver_pub || sender_pub, 32)
  const ikm = await hkdfExpand(
    prkKey,
    concat(new TextEncoder().encode('WebPush: info\x00'), receiverPubRaw, senderPubRaw),
    32
  );

  const salt = crypto.getRandomValues(new Uint8Array(16));

  // PRK = HMAC(salt, IKM)
  const prk = await hmac256(salt, ikm);

  // CEK (16 bytes) e NONCE (12 bytes)
  const cek   = await hkdfExpand(prk, new TextEncoder().encode('Content-Encoding: aes128gcm\x00'), 16);
  const nonce = await hkdfExpand(prk, new TextEncoder().encode('Content-Encoding: nonce\x00'), 12);

  const aesKey = await crypto.subtle.importKey('raw', cek, { name: 'AES-GCM' }, false, ['encrypt']);
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce },
    aesKey,
    concat(payloadBytes, new Uint8Array([2])) // 0x02 = last-record delimiter
  ));

  // RFC 8188 header: salt(16) || rs(4 BE) || idlen(1) || sender_pub(65)
  const header = new Uint8Array(21 + senderPubRaw.length);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, 4096, false);
  header[20] = senderPubRaw.length;
  header.set(senderPubRaw, 21);

  const body = concat(header, ciphertext);

  // ── VAPID JWT (RFC 8292) ──────────────────────────────────────────────────
  const pubBytes = fromb64u(vapidPublicKey); // 65 bytes: 0x04 || x(32) || y(32)
  const privBytes = fromb64u(vapidPrivateKey); // 32 bytes

  const signingKey = await crypto.subtle.importKey(
    'jwk',
    {
      kty: 'EC', crv: 'P-256',
      x: b64u(pubBytes.slice(1, 33)),
      y: b64u(pubBytes.slice(33, 65)),
      d: b64u(privBytes),
      key_ops: ['sign']
    },
    { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']
  );

  const audience = new URL(subscription.endpoint).origin;
  const exp = Math.floor(Date.now() / 1000) + 12 * 3600;
  const jwtHead = b64u(new TextEncoder().encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const jwtBody = b64u(new TextEncoder().encode(JSON.stringify({ aud: audience, exp, sub: vapidSubject })));
  const unsigned = `${jwtHead}.${jwtBody}`;

  const rawSig = new Uint8Array(await crypto.subtle.sign(
    { name: 'ECDSA', hash: { name: 'SHA-256' } }, signingKey,
    new TextEncoder().encode(unsigned)
  ));
  const jwt = `${unsigned}.${b64u(rawSig)}`;

  return fetch(subscription.endpoint, {
    method: 'POST',
    headers: {
      'Authorization': `vapid t=${jwt},k=${vapidPublicKey}`,
      'Content-Type': 'application/octet-stream',
      'Content-Encoding': 'aes128gcm',
      'TTL': '86400',
    },
    body,
  });
}

// ── CORS ─────────────────────────────────────────────────────────────────────
function corsHeaders(origin, allowed) {
  const ok = origin === allowed || origin.startsWith('http://localhost');
  return {
    'Access-Control-Allow-Origin': ok ? origin : '',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

// ── Worker ───────────────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const cors = corsHeaders(origin, env.ALLOWED_ORIGIN || '');

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/subscribe') {
      const { subscription, events } = await request.json();
      const now = Date.now();
      const futureEvents = events.filter(e => new Date(e.isoTime).getTime() > now);
      await env.STORE.put('data', JSON.stringify({ subscription, events: futureEvents }));
      return new Response('OK', { status: 200, headers: cors });
    }

    return new Response('Not Found', { status: 404, headers: cors });
  },

  async scheduled(event, env) {
    const data = await env.STORE.get('data', { type: 'json' });
    if (!data?.subscription || !data?.events?.length) return;

    const now = Date.now();

    for (const ev of data.events) {
      const diffH = (new Date(ev.isoTime).getTime() - now) / 3_600_000;

      let notification = null;

      if (diffH >= 23.5 && diffH <= 24.5) {
        const time = new Date(ev.isoTime).toLocaleString('pt-BR', {
          hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo'
        });
        notification = {
          title: '🏥 Plantão HVC — 24h',
          body: `${ev.label} ${ev.hours} · amanhã às ${time}`
        };
      } else if (diffH >= 0.5 && diffH <= 1.5) {
        const time = new Date(ev.isoTime).toLocaleString('pt-BR', {
          hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo'
        });
        notification = {
          title: '🏥 Plantão HVC — 1h',
          body: `${ev.label} ${ev.hours} · começa às ${time}`
        };
      }

      if (!notification) continue;

      try {
        const resp = await sendPush(
          data.subscription, notification,
          env.VAPID_PUBLIC_KEY, env.VAPID_PRIVATE_KEY, env.VAPID_SUBJECT
        );
        if (resp.status === 410) {
          // Subscription expirada — limpar KV
          await env.STORE.delete('data');
          return;
        }
      } catch (err) {
        console.error('Push failed:', err.message);
      }
    }
  }
};
```

- [ ] **Step 2: Commit**

```bash
git add notifications-worker/
git commit -m "feat: add Cloudflare Worker with Web Push implementation"
```

---

## Task 4: Atualizar index.html — registerNotifications()

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Adicionar constantes VAPID_PUBLIC_KEY e WORKER_URL**

Em `index.html`, localizar o bloco CONFIG no início do `<script>` (linhas 142–145):

```javascript
var CLIENT_ID = '175749909419-...';
var SCOPES = 'https://www.googleapis.com/auth/calendar.readonly';
var PEGA_CAL_ID = '046759683cb23c692...';
// =============================================
```

Adicionar logo após o comentário `// =============================================`:

```javascript
var VAPID_PUBLIC_KEY = 'PASTE_PUBLIC_KEY_HERE'; // substituir após Task 5
var WORKER_URL = 'PASTE_WORKER_URL_HERE';        // substituir após Task 5
```

- [ ] **Step 2: Adicionar urlBase64ToUint8Array e registerNotifications()**

Localizar a linha `loadGsi();` no final do `<script>` (linha 567). Inserir **antes** dela:

```javascript
function urlBase64ToUint8Array(b64) {
  var padding = '='.repeat((4 - b64.length % 4) % 4);
  var base64 = (b64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(base64), function(c) { return c.charCodeAt(0); });
}

async function registerNotifications() {
  if (!('Notification' in window) || !('PushManager' in window)) return;
  if (Notification.permission === 'denied') return;
  if (!VAPID_PUBLIC_KEY || VAPID_PUBLIC_KEY.startsWith('PASTE')) return;
  if (!WORKER_URL || WORKER_URL.startsWith('PASTE')) return;

  try {
    var permission = await Notification.requestPermission();
    if (permission !== 'granted') return;

    var reg = await navigator.serviceWorker.ready;
    var subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
    });

    var tK = todayK();
    var events = [];
    Object.keys(HVC).sort().forEach(function(key) {
      if (key < tK) return;
      var hvc = HVC[key];
      var startHour = parseInt(hvc.hours.split('h')[0], 10);
      var isoTime = new Date(key + 'T' + pad2(startHour) + ':00:00-03:00').toISOString();
      events.push({ isoTime: isoTime, label: hvc.label, hours: hvc.hours, source: hvc.source });
    });

    await fetch(WORKER_URL + '/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription: subscription.toJSON(), events: events })
    });
  } catch(e) {
    // Notificações são best-effort; falha silenciosa
  }
}
```

- [ ] **Step 3: Chamar registerNotifications() ao final de loadData()**

Localizar o final da função `loadData()` (em torno da linha 381):

```javascript
  render();
}
```

Substituir por:

```javascript
  render();
  registerNotifications();
}
```

- [ ] **Step 4: Commit com valores placeholder (serão preenchidos após Task 5)**

```bash
git add index.html
git commit -m "feat: add push notification registration to PWA (placeholder keys)"
```

---

## Task 5: Setup no Cloudflare via Playwright MCP

**Files:** nenhum (configuração no dashboard)

- [ ] **Step 1: Navegar e fazer login**

```
playwright: browser_navigate → https://dash.cloudflare.com
```

Fazer login ou criar conta gratuita (não requer cartão).

- [ ] **Step 2: Criar o Worker**

Navegar: Workers & Pages → Overview → Create application → Create Worker.
Nome: `agenda-arthur-notifications`. Clicar em Deploy (ignorar o hello-world).

Anotar a URL do Worker: `https://agenda-arthur-notifications.USERNAME.workers.dev`

- [ ] **Step 3: Criar namespace KV**

Navegar: Workers & Pages → KV → Create namespace.
Nome: `STORE`. Clicar em Add.

- [ ] **Step 4: Vincular KV ao Worker**

Navegar: Workers & Pages → agenda-arthur-notifications → Settings → Variables → KV Namespace Bindings.
Adicionar: Variable name = `STORE`, KV Namespace = `STORE`. Salvar.

- [ ] **Step 5: Adicionar variáveis de ambiente**

Em Settings → Variables → Environment Variables → Add variable:

| Variable | Value | Type |
|----------|-------|------|
| `VAPID_PUBLIC_KEY` | chave pública da Task 1 | Plain text |
| `VAPID_SUBJECT` | `mailto:arthurkingayres@gmail.com` | Plain text |
| `ALLOWED_ORIGIN` | `https://USERNAME.github.io` (URL real do GitHub Pages) | Plain text |

- [ ] **Step 6: Adicionar secret**

Em Settings → Variables → Environment Variables → Add variable (tipo Encrypt):

| Variable | Value | Type |
|----------|-------|------|
| `VAPID_PRIVATE_KEY` | chave privada da Task 1 | Encrypt (secret) |

Salvar e fazer Deploy para aplicar as variáveis.

- [ ] **Step 7: Configurar cron trigger**

Em Settings → Triggers → Cron Triggers → Add Cron Trigger.
Expressão: `0 * * * *`. Salvar.

- [ ] **Step 8: Colar o código do Worker e fazer deploy**

Em Edit Code (editor online do Worker):
- Apagar o código hello-world existente
- Colar o conteúdo completo de `notifications-worker/src/index.js` da Task 3
- Clicar em Deploy

---

## Task 6: Preencher VAPID_PUBLIC_KEY e WORKER_URL no index.html

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Substituir placeholders com valores reais**

Localizar em `index.html`:

```javascript
var VAPID_PUBLIC_KEY = 'PASTE_PUBLIC_KEY_HERE';
var WORKER_URL = 'PASTE_WORKER_URL_HERE';
```

Substituir pelos valores reais obtidos nas Tasks 1 e 5:

```javascript
var VAPID_PUBLIC_KEY = 'BChavePublicaRealDa65BytesAquiBase64Url...';
var WORKER_URL = 'https://agenda-arthur-notifications.USERNAME.workers.dev';
```

- [ ] **Step 2: Commit e push para GitHub Pages**

```bash
git add index.html
git commit -m "feat: wire VAPID public key and Worker URL"
git push origin main
```

GitHub Pages publica em ~30 segundos.

---

## Task 7: Teste end-to-end no iPhone

**Files:** nenhum

- [ ] **Step 1: Reinstalar o PWA no iPhone**

No Safari do iPhone, abrir `https://USERNAME.github.io/REPO_NAME/`.
Se o PWA já estava instalado na tela inicial, remover e adicionar novamente (para forçar instalação do novo service worker `v2`).

- [ ] **Step 2: Verificar diálogo de permissão**

Após o login, o iOS deve exibir o diálogo do sistema "Allow Notifications".
Tocar em "Allow".

- [ ] **Step 3: Verificar subscription no KV**

No Cloudflare dashboard → Workers & Pages → agenda-arthur-notifications → Workers KV (ou via a aba KV da namespace `STORE`):
Verificar que a chave `data` existe e contém JSON com `subscription` e `events`.

- [ ] **Step 4: Disparar cron manualmente para testar**

No Cloudflare dashboard → Workers & Pages → agenda-arthur-notifications → Triggers → Cron Triggers → clicar em "Trigger" (execução manual).

Se nenhum plantão estiver a 24h/1h de distância exata, verificar os logs da execução. Para confirmar o fluxo de ponta a ponta, editar temporariamente o Worker (no dashboard) substituindo as condições de janela:

```javascript
// Temporário — disparar para qualquer evento futuro
if (diffH >= 0.5 && diffH <= 500) {
  notification = { title: '🏥 Plantão HVC — TESTE', body: `${ev.label} ${ev.hours}` };
}
```

Verificar se a notificação aparece no iPhone. Após confirmação, remover a condição de teste e fazer deploy novamente.
