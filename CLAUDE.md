# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PWA pessoal do Arthur (médico residente) que consolida em uma única tela mensal:

- **SOBREAVISOS** — escala de sobreaviso da UNICAMP (CPL), origem: Google Sheets "Sobreavisos CPL 2026".
- **HVC** — plantões particulares no Hospital Vera Cruz, origem: Google Calendar "Pega Plantão" (`PEGA_CAL_ID` em [index.html:151](index.html#L151)).

Hospedado em GitHub Pages: <https://arthurkingayres-ux.github.io/agenda-consolidada/> — auto-deploy de `main`, sem build step, sem CI. Push direto em `main` é o fluxo normal de release.

## Layout do repo

| Arquivo | Função |
|---|---|
| `index.html` | App inteiro (HTML + CSS + JS inline). É o único arquivo que importa pro produto. |
| `sw.js` | Service worker. Network-first com cache offline. |
| `manifest.json`, `icon-*.png/svg` | Metadata PWA. |
| `notifications-worker/src/index.js` | Cloudflare Worker que faz Web Push (RFC 8291 + 8292 com Web Crypto API; sem deps npm). Sem `wrangler.toml` no repo — config vive no dashboard Cloudflare. |
| `routines/daily-sync-sobreavisos.md` | Fonte versionada do prompt da cloud routine. Não é lida em runtime. |
| `docs/superpowers/{specs,plans}/` | Specs e planos de features passadas. Histórico, não normativo. |

Os PNGs na raiz são screenshots de setup de uma sessão passada — ignore, não são referenciados em lugar nenhum.

## Comandos

Não tem build, lint ou test suite. Para dev local:

```bash
# Servir o site (qualquer static server). O SW precisa de HTTP, não file://
python -m http.server 8000   # depois abre http://localhost:8000

# Worker de push (precisa de wrangler instalado globalmente; config no dashboard CF)
cd notifications-worker && wrangler dev
cd notifications-worker && wrangler deploy
```

Forçar refresh do PWA em produção: bumpar `CACHE` em [sw.js:1](sw.js#L1) (`agenda-arthur-vN` → `vN+1`).

## Como SOBREAVISOS e HVC convivem

São duas fontes que produzem dicts independentes mergidos no render:

- **`SOBREAVISOS`** (hardcoded em [index.html:160](index.html#L160) até `};`): dict `{ "YYYY-MM-DD": {"t":"full"} | {"t":"partial","h":"19h-7h"} }`. **NÃO edite à mão.** É reescrito automaticamente pela cloud routine (ver seção abaixo).
- **`HVC`** (construído em runtime em `loadData()` ~[index.html:324](index.html#L324)): puxa eventos do Google Calendar via OAuth, classifica por horário (`HVC Noturno`/`Diurno`/`Tarde`/`Tarde+Noturno`), e calcula `weight = duração / 12`. Se faltarem eventos reais num mês, cai pra projeção sintética em cima dos slots semanais.

## Regra de peso de plantão (HVC)

1 plantão = 12 h. Peso de cada evento HVC = `duração / 12`. Exemplos: 6h → 0,5; 12h → 1; 18h → 1,5; 24h → 2. Taxa atual: **R$ 1.700 por plantão (peso 1)**. A contagem ponderada é o que vira "X plantões" na UI e nos cálculos de receita projetada — não confunda com contagem bruta de eventos.

## Service Worker — caching

Estratégia atual (v8 em diante): **network-first**. `fetch` tenta a rede primeiro e atualiza o cache; só serve do cache se a rede falhar.

**Não reverta pra cache-first sem antes ler [memory/project_pwa_sw_caching.md](.claude/projects/c--Users-absay-Documents-Agenda-Consolidada/memory/project_pwa_sw_caching.md).** O motivo: a routine de sync mexe em `index.html` duas vezes por semana; com cache-first, o cache antigo continua servindo a versão antiga indefinidamente (foi exatamente isso que quebrou o PWA até 2026-05-19). Network-first elimina a necessidade de bumpar `CACHE` em cada sync.

`CACHE` continua sendo bumpado manualmente apenas quando `sw.js` em si muda.

## Cloud routine — sync do SOBREAVISOS

**Routine ID:** `trig_01HE517n6Ca6ot2HorZ9v2Pa` · **Cadência:** seg+qui 06:57 BRT (cron `57 9 * * 1,4` UTC) · **Painel:** <https://claude.ai/code/routines/trig_01HE517n6Ca6ot2HorZ9v2Pa>

Fluxo: a routine lê a planilha do Sheets via conector Google Drive, monta o novo dict `SOBREAVISOS`, edita `index.html`, abre PR pra `main` e roda `gh pr merge --squash --delete-branch` (a sandbox CCR não permite push direto em `main`).

Quando precisar ajustar o comportamento da routine:

1. Editar `routines/daily-sync-sobreavisos.md` (fonte versionada).
2. Colar o prompt novo em `claude.ai/code/routines` → Edit (ou via `RemoteTrigger update`). O arquivo no repo **não é lido em runtime**.

Histórico de incidentes relevantes está em [memory/project_daily_sync_routine.md](.claude/projects/c--Users-absay-Documents-Agenda-Consolidada/memory/project_daily_sync_routine.md).

## Push notifications

PWA pede permissão → assina no push service do browser → POST pra `notifications-worker` com a subscription → worker armazena no Cloudflare KV. O worker depois envia notificações via Web Push (criptografia inline em `notifications-worker/src/index.js`). VAPID public key e URL do worker estão hardcoded em [index.html:153](index.html#L153)-[154](index.html#L154).

iOS adiciona pegadinhas: `requestPermission` precisa de user gesture, e há um histórico de bugs já resolvidos sobre install do SW e banner de status (ver commits recentes `fix:` em `git log -- sw.js index.html`).

## Convenções

- **Linguagem:** PT-BR em commits, comentários, UI e documentação.
- **Commits:** prefixo `fix:`/`feat:`/`chore(data):` (chore(data) é reservado pra commits da routine).
- **Versionamento do SW:** só bumpa `CACHE` quando `sw.js` muda; mudanças em `index.html` não precisam bump (network-first cuida).
