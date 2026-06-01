# Notificações de sobreaviso — design

**Data:** 2026-06-01
**Objetivo:** Estender os lembretes push (24h antes e 1h antes) — hoje só para plantões HVC — para também cobrir os sobreavisos da UNICAMP (dict `SOBREAVISOS`).

## Contexto

Hoje o fluxo de push é:

1. Client ([index.html](../../../index.html)) monta `events: [{isoTime, label, hours, source}]` apenas a partir do dict `HVC` ([index.html:662-670](../../../index.html#L662-L670)) e faz POST em `WORKER_URL/subscribe`.
2. Worker ([notifications-worker/src/index.js](../../../notifications-worker/src/index.js)) guarda `{subscription, events}` no KV (chave única `data` — app de usuário único).
3. `scheduled()` roda de hora em hora; para cada evento calcula `diffH` até `isoTime` e dispara push se cair na janela `[23.5, 24.5]` (24h) ou `[0.5, 1.5]` (1h). Título hardcoded `🏥 Plantão HVC`.

O dict `SOBREAVISOS` nunca entra na lista de eventos.

### Por que não dá para reusar o modelo atual no caso 24h de FDS

O sobreaviso 24h de fim de semana começa à meia-noite (`00:00`). Os dois lembretes desejados (véspera ~19h e véspera ~23h) estão a **4h** um do outro, mas "24h antes" e "1h antes" de um mesmo instante estão sempre a **23h** de distância. Logo, é impossível derivar ambos de uma única âncora `00:00` com o modelo de janelas fixas do Worker.

Solução: mover o cálculo de datas/horários para o **client** (onde mexer com `Date` é trivial e todos os dados já existem) e deixar o Worker burro — ele só dispara lembretes já resolvidos.

## Decisões tomadas (brainstorming)

- **Âncora do sobreaviso 24h de FDS:** véspera às 19h (lembrete "amanhã") + véspera às 23h (lembrete "1h").
- **Dia com HVC + sobreaviso simultâneos:** notificações separadas (cada fonte gera seu par 24h/1h).
- **Rótulo:** `🩺 Sobreaviso CPL` distinto do `🏥 Plantão HVC`.

## Arquitetura

### 1. Novo contrato de evento (client → Worker)

Cada evento carrega seus lembretes já resolvidos (horário de disparo + título + corpo prontos):

```js
{
  type: 'hvc' | 'sobreaviso',          // metadado; não estritamente necessário ao Worker
  reminders: [
    { fire: '2026-06-05T18:00:00-03:00', title: '🩺 Sobreaviso CPL — 24h', body: 'Sobreaviso noturno 19h-7h · amanhã às 19:00' },
    { fire: '2026-06-06T18:00:00-03:00', title: '🩺 Sobreaviso CPL — 1h',  body: 'Sobreaviso noturno 19h-7h · começa às 19:00' }
  ]
}
```

Unifica HVC e sobreaviso no mesmo mecanismo e remove toda lógica de data/formatação do Worker.

**Migração:** app de usuário único; `registerNotifications()` roda a cada load quando a permissão já foi concedida ([index.html:388-390](../../../index.html#L388-L390)), sobrescrevendo o KV. Logo o formato antigo some assim que Arthur reabre o PWA. Não é preciso migração explícita no Worker. Ordem de deploy recomendada: Worker primeiro, depois push do client (network-first atualiza o client rápido). Durante a janela de transição pode haver algumas horas sem lembrete — aceitável.

### 2. Cálculo dos lembretes (client)

Função nova `buildReminders(startDate, leadKindCivil, titlePrefix, bodyDesc)` (nome final livre) que, dada a data/hora de início de um evento, devolve a lista de `reminders`.

Regra geral (HVC e sobreaviso com início "civil" — noturno 19h, parcial Xh-Yh, diurno 7h):

- **24h antes:** `fire = start − 24h`; título `{prefix} — 24h`; corpo `{desc} · amanhã às {HH:MM do start}`.
- **1h antes:** `fire = start − 1h`; título `{prefix} — 1h`; corpo `{desc} · começa às {HH:MM do start}`.

Caso especial — **sobreaviso 24h de FDS** (início `00:00`):

- **Lembrete "amanhã":** `fire = véspera 19:00` (= start − 5h); título `🩺 Sobreaviso CPL — amanhã`; corpo `Sobreaviso 24h · começa amanhã 00:00`.
- **Lembrete "1h":** `fire = véspera 23:00` (= start − 1h); título `🩺 Sobreaviso CPL — 1h`; corpo `Sobreaviso 24h · começa à meia-noite`.

Determinação da hora de início do sobreaviso — reusa exatamente a lógica de [index.html:378](../../../index.html#L378):

```js
var dw = new Date(key + 'T12:00:00').getDay();
var sR = sob.t === 'partial' ? phr(sob.h) : (dw===0||dw===6 ? {s:0,e:24} : {s:19,e:31});
// startHour = sR.s   (0 → caso FDS especial; 19 → noturno; phr(h).s → parcial)
```

Descrição (`desc`) para o corpo do sobreaviso:

- `full` + FDS → `Sobreaviso 24h`
- `full` + dia de semana → `Sobreaviso noturno 19h-7h`
- `partial` → `Sobreaviso parcial {h}` (ex. `Sobreaviso parcial 7h-13h`)

Filtragem: descarta `reminders` cujo `fire <= agora` (espelha o filtro `key < tK` atual; eventos de dias já passados não geram lembrete).

### 3. Montagem da lista de eventos (client)

Em `registerNotifications()` ([index.html:662-670](../../../index.html#L662-L670)), além do loop sobre `HVC`, adicionar loop sobre `SOBREAVISOS`:

- HVC: `type:'hvc'`, prefixo `🏥 Plantão HVC`, `desc = '{label} {hours}'`, início = `parseInt(hvc.hours)`.
- Sobreaviso: `type:'sobreaviso'`, prefixo `🩺 Sobreaviso CPL`, `desc` conforme acima, início conforme regra do `phr`/FDS.

Cada um chama `buildReminders`. Eventos sem nenhum lembrete futuro são omitidos.

### 4. Worker simplificado

`scheduled()`:

```js
const now = Date.now();
for (const ev of data.events) {
  for (const r of (ev.reminders || [])) {
    const diffH = (new Date(r.fire).getTime() - now) / 3_600_000;
    if (diffH >= -0.5 && diffH <= 0.5) {        // ±30min — 1h de largura, igual hoje
      const resp = await sendPush(data.subscription, { title: r.title, body: r.body }, ...);
      if (resp.status === 410) { await env.STORE.delete('data'); return; }
    }
  }
}
```

`/subscribe`: poda lembretes passados e descarta eventos sem lembrete futuro:

```js
const futureEvents = events
  .map(e => ({ ...e, reminders: (e.reminders || []).filter(r => new Date(r.fire).getTime() > now) }))
  .filter(e => e.reminders.length > 0);
```

Some todo o branching de 24h/1h e a formatação de hora (`toLocaleString`) do Worker — agora vem pronto do client.

### 5. UI

Atualizar o texto do prompt em [index.html:424](../../../index.html#L424):

`🔔 Ativar lembretes (24h e 1h antes de cada plantão HVC)`
→ `🔔 Ativar lembretes (24h e 1h antes de cada plantão HVC e sobreaviso)`

## Fluxo de dados

```
SOBREAVISOS (dict hardcoded) ─┐
                               ├─► registerNotifications() ─► buildReminders() ─► events[] ─► POST /subscribe ─► KV
HVC (runtime, loadData) ──────┘                                                                                    │
                                                                                                                   ▼
                                                            cron horário ─► scheduled() ─► para cada reminder due ─► sendPush
```

## Tratamento de erros / edge cases

- **Reminder no passado:** podado no `/subscribe` e ignorado no `scheduled()` (diffH fora de ±0.5).
- **Disparo duplo:** janela de 1h de largura com cron horário pode, em alinhamento de borda, disparar duas vezes — mesmo comportamento de hoje; não se introduz dedup (paridade com o atual).
- **Subscription expirada (410):** limpa o KV — inalterado.
- **Formato antigo no KV:** `ev.reminders` ausente → loop interno não roda; sem erro. Sobrescrito no próximo load.
- **Sobreaviso 24h de FDS começando hoje:** se Arthur abrir o app no próprio FDS, os lembretes da véspera já passaram → podados. Comportamento correto.

## Versionamento

- `notifications-worker` muda → `wrangler deploy`.
- `index.html` muda → push direto em `main` (network-first cuida do cache; sem bump de `CACHE` em `sw.js`).

## Testes

Sem suíte automatizada no repo. Verificação manual:

1. Inspecionar o array `events` montado no client (console) num mês com sobreaviso noturno, parcial e 24h de FDS — conferir `fire`/`title`/`body` de cada caso.
2. Conferir que os `fire` calculados batem: noturno 19h → 18h véspera + 18h dia; FDS 24h → 19h véspera + 23h véspera.
3. (Opcional) `wrangler dev` + chamada manual de `scheduled` com `fire` próximo de agora para confirmar disparo e copy.

## Fora de escopo (YAGNI)

- Dedup de disparo no Worker.
- Notificações agrupadas (HVC + sobreaviso no mesmo push) — decidido: separadas.
- Configuração de horário de âncora pelo usuário.
- Migração explícita de formato antigo no KV.
