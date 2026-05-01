# Design: Push Notifications para Plantões HVC

**Data:** 2026-05-01  
**Escopo:** Notificações push no iPhone (PWA instalado) 24h e 1h antes de cada plantão HVC. Sobreavisos não são notificados.

---

## Arquitetura

```
iPhone (PWA instalado na tela inicial)
  → login Google → showDashboard() → registerNotifications()
  → Apple Push Service → PushSubscription
  → POST /subscribe com {subscription, events[]}
        ↓
  Cloudflare Worker (workers.dev — grátis)
    KV: salva subscription + lista de timestamps HVC
    Cron: 0 * * * * → verifica timestamps → envia Web Push
        ↓
  Apple Push Service → notificação no iPhone
```

Três peças: PWA (GitHub Pages), Service Worker, Cloudflare Worker + KV.

---

## Peça 1 — `index.html`

### Registro automático

`registerNotifications()` é chamada ao **final de `loadData()`**, após o objeto `HVC` estar completamente populado (real + projeções). Não pode ser chamada antes, pois depende do `HVC` para extrair os timestamps dos plantões.

Fluxo:
1. Verifica `'Notification' in window && 'PushManager' in window`. Se não suportado, silencia.
2. Chama `Notification.requestPermission()`. Se negado, silencia (sem alertas).
3. Busca service worker registration via `navigator.serviceWorker.ready`.
4. Chama `registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY) })`.
5. Coleta eventos HVC futuros do objeto `HVC` (já computado em memória):
   - Para cada chave `key` em `HVC` onde `key >= todayK()`:
     - Extrai hora de início do campo `hours` (ex: `"19h-07h"` → `19`)
     - Constrói `isoTime = new Date(key + 'T' + pad2(startHour) + ':00:00-03:00').toISOString()`
     - Inclui `{ isoTime, label: hvc.label, hours: hvc.hours, source: hvc.source }`
6. Faz `POST WORKER_URL/subscribe` com JSON `{ subscription, events }`.

### Re-envio no refresh

O handler do botão "↻ Atualizar dados" chama `registerNotifications()` após `loadData()` terminar, se `Notification.permission === 'granted'`.

### Constantes adicionadas

```js
var VAPID_PUBLIC_KEY = 'BExemplo...'; // chave pública VAPID gerada uma vez
var WORKER_URL = 'https://agenda-arthur-notifications.USUARIO.workers.dev';
```

---

## Peça 2 — `sw.js`

Adiciona handler do evento `push`:

```js
self.addEventListener('push', function(e) {
  var data = e.data ? e.data.json() : {};
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

Versão do cache atualizada de `agenda-arthur-v1` para `agenda-arthur-v2` para forçar reinstalação do SW.

---

## Peça 3 — Cloudflare Worker

### Estrutura de arquivos

```
notifications-worker/
  src/index.js
  wrangler.toml
  package.json
```

### `wrangler.toml`

```toml
name = "agenda-arthur-notifications"
main = "src/index.js"
compatibility_date = "2024-01-01"

[[kv_namespaces]]
binding = "STORE"
id = "ID_GERADO_PELO_WRANGLER"

[triggers]
crons = ["0 * * * *"]
```

### `src/index.js` — rotas

**`POST /subscribe`**
- Valida CORS: aceita apenas `https://USUARIO.github.io` (e `localhost` para dev)
- Lê `{ subscription, events }` do body
- Filtra `events` para apenas datas futuras (previne acúmulo de timestamps passados)
- Salva em KV: `await STORE.put('data', JSON.stringify({ subscription, events }))`
- Retorna `200 OK`

**`OPTIONS /subscribe`**
- Responde com headers CORS corretos (preflight)

### `src/index.js` — cron

```
scheduled handler:
  1. Lê KV: data = await STORE.get('data', 'json')
  2. Se sem data ou sem subscription, retorna
  3. Para cada event em data.events:
     a. diff = new Date(event.isoTime) - new Date()
     b. Se 23.5h ≤ diff ≤ 24.5h → envia push "24h antes"
     c. Se 0.5h ≤ diff ≤ 1.5h  → envia push "1h antes"
  4. Envia via web-push com VAPID_PRIVATE_KEY + VAPID_SUBJECT (env secrets)
```

**Payload da notificação:**
```json
{
  "title": "🏥 Plantão HVC — 24h",
  "body": "HVC Noturno 19h-07h · amanhã às 19h"
}
```
ou
```json
{
  "title": "🏥 Plantão HVC — 1h",
  "body": "HVC Noturno 19h-07h · começa às 19h"
}
```

### Dependências

```json
{ "web-push": "^3.6.7" }
```

### Segredos (via `wrangler secret put`)

| Secret | Valor |
|--------|-------|
| `VAPID_PRIVATE_KEY` | chave privada gerada por `npx web-push generate-vapid-keys` |
| `VAPID_SUBJECT` | `mailto:arthurkingayres@gmail.com` |

---

## Setup (uma vez só)

1. `npm install -g wrangler` → `wrangler login`
2. `npx web-push generate-vapid-keys` → anota pública e privada
3. `wrangler kv:namespace create STORE` → copia o ID para `wrangler.toml`
4. `wrangler secret put VAPID_PRIVATE_KEY`
5. `wrangler secret put VAPID_SUBJECT`
6. `wrangler deploy`
7. Atualiza `VAPID_PUBLIC_KEY` e `WORKER_URL` em `index.html`
8. Commit e push para GitHub Pages

---

## Limitações e trade-offs

- **Projeções sem horário preciso:** plantões projetados têm hora extraída do campo `hours` (ex: "19h-07h" → `19:00`). Suficientemente preciso para notificação.
- **Subscription expira:** se o iOS revogar a subscription (raro), o próximo acesso ao PWA renova automaticamente via `showDashboard()`.
- **Cron ±30min de tolerância:** o cron roda a cada hora cheia. A janela de ±30min garante que o evento seja detectado mesmo que o plantão comece em hora não-cheia.
- **Um único usuário:** KV usa chave fixa `"data"`. Sem necessidade de autenticação no Worker.
- **CORS restrito ao domínio do GitHub Pages:** previne que outras origens registrem subscriptions.
