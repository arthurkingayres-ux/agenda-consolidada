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
| `scripts/sync_sobreavisos.py` | Sync do dict `SOBREAVISOS` a partir da planilha. Rodado pelo GitHub Actions. |
| `tests/` | Suíte do parser (37 testes, só stdlib). `tests/fixtures/sheet.json` é a grade real **anonimizada**. |
| `.github/workflows/` | `sync-sobreavisos.yml` (cron seg/qui) e `tests.yml` (push/PR). |
| `routines/daily-sync-sobreavisos.md` | Prompt da cloud routine **desativada** em 2026-07-23. Histórico. |
| `docs/superpowers/{specs,plans}/` | Specs e planos de features passadas. Histórico, não normativo. |

Os PNGs na raiz são screenshots de setup de uma sessão passada — ignore, não são referenciados em lugar nenhum.

## Comandos

Sem build e sem lint. Testes existem só para o sync:

```bash
# Suíte do parser — não precisa de credencial nem de pip install
python -m unittest discover -s tests

# Servir o site (qualquer static server). O SW precisa de HTTP, não file://
python -m http.server 8000   # depois abre http://localhost:8000

# Sync local (precisa de GOOGLE_SERVICE_ACCOUNT_KEY no ambiente)
pip install google-auth requests
python scripts/sync_sobreavisos.py --dry-run

# Worker de push (precisa de wrangler instalado globalmente; config no dashboard CF)
cd notifications-worker && wrangler dev
cd notifications-worker && wrangler deploy
```

Forçar refresh do PWA em produção: bumpar `CACHE` em [sw.js:1](sw.js#L1) (`agenda-arthur-vN` → `vN+1`).

## Como SOBREAVISOS e HVC convivem

São duas fontes que produzem dicts independentes mergidos no render:

- **`SOBREAVISOS`** (hardcoded em [index.html:162](index.html#L162) até `};`): dict `{ "YYYY-MM-DD": {"t":"full"} | {"t":"partial","h":"19h-7h"} }`. **NÃO edite à mão.** É reescrito pelo GitHub Actions (ver seção abaixo). Se editar, o próximo sync sobrescreve — corrija na planilha, não aqui.
- **`HVC`** (construído em runtime em `loadData()` ~[index.html:324](index.html#L324)): puxa eventos do Google Calendar via OAuth, classifica por horário (`HVC Noturno`/`Diurno`/`Tarde`/`Tarde+Noturno`), e calcula `weight = duração / 12`. Se faltarem eventos reais num mês, cai pra projeção sintética em cima dos slots semanais.

## Regra de peso de plantão (HVC)

1 plantão = 12 h. Peso de cada evento HVC = `duração / 12`. Exemplos: 6h → 0,5; 12h → 1; 18h → 1,5; 24h → 2. Taxa atual: **R$ 1.700 por plantão (peso 1)**. A contagem ponderada é o que vira "X plantões" na UI e nos cálculos de receita projetada — não confunda com contagem bruta de eventos.

## Service Worker — caching

Estratégia atual (v8 em diante): **network-first**. `fetch` tenta a rede primeiro e atualiza o cache; só serve do cache se a rede falhar.

**Não reverta pra cache-first sem antes ler [memory/project_pwa_sw_caching.md](.claude/projects/c--Users-absay-Documents-Agenda-Consolidada/memory/project_pwa_sw_caching.md).** O motivo: o sync mexe em `index.html` duas vezes por semana; com cache-first, o cache antigo continua servindo a versão antiga indefinidamente (foi exatamente isso que quebrou o PWA até 2026-05-19). Network-first elimina a necessidade de bumpar `CACHE` em cada sync. Vale igual com o Actions no lugar da routine.

`CACHE` continua sendo bumpado manualmente apenas quando `sw.js` em si muda.

## Sync do SOBREAVISOS — GitHub Actions

**Workflow:** `.github/workflows/sync-sobreavisos.yml` · **Cadência:** seg+qui 06:57 BRT (cron `57 9 * * 1,4` UTC) · **Manual:** `gh workflow run "Sync SOBREAVISOS" -f dry_run=true`

Fluxo: roda os testes → lê a planilha pela **Sheets API** (`values.batchGet` + ranges de merge) → parseia → valida → reescreve o bloco em `index.html` → commita direto em `main`. Em qualquer falha aborta sem tocar no arquivo e abre issue (com dedup por título).

**Auth:** service account `sobreavisos-reader@sobreavisos-sync.iam.gserviceaccount.com`, projeto GCP `sobreavisos-sync` (isolado do projeto do PWA). A planilha está compartilhada como Leitor com esse e-mail. A chave está no secret `GOOGLE_SERVICE_ACCOUNT_KEY`. Nada expira; não há consent screen no caminho.

**Quando o layout da planilha mudar** (a Action vai falhar e abrir issue):

```bash
python scripts/sync_sobreavisos.py --dump-fixture tests/fixtures/sheet.json  # anonimiza por padrão
python -m unittest discover -s tests
```

Ajuste o parser com o teste golden falhando até voltar a passar. **A fixture é anonimizada de propósito** — o repo é público e a planilha traz a escala de todos os plantonistas do CPL. Nunca commite `--no-redact`.

Detalhes que o parser depende e que não são óbvios:

- Rótulo e nome vivem na **mesma célula** (`P2: Arthur`), e a classificação é **por célula, nunca por linha**: em turno dividido a planilha insere uma linha P2 extra que, nas outras colunas, carrega o `Chefe:` daquele dia.
- Células mescladas: o `values.batchGet` só preenche a âncora, por isso os ranges de merge são buscados à parte e expandidos em memória.
- Horário torto (`Arthur 7h-13h)`, sem abre-parêntese) é tolerado **e reportado** como `AVISO` no log da run.

**A cloud routine (`trig_01HE517n6Ca6ot2HorZ9v2Pa`) foi desativada em 2026-07-23** após 7 incidentes em ~13 semanas, todos na camada harness/MCP/sandbox. Histórico em [memory/project_daily_sync_routine.md](.claude/projects/c--Users-absay-Documents-Agenda-Consolidada/memory/project_daily_sync_routine.md). O prompt fica em `routines/` só como referência.

## Push notifications

PWA pede permissão → assina no push service do browser → POST pra `notifications-worker` com a subscription → worker armazena no Cloudflare KV. O worker depois envia notificações via Web Push (criptografia inline em `notifications-worker/src/index.js`). VAPID public key e URL do worker estão hardcoded em [index.html:153](index.html#L153)-[154](index.html#L154).

iOS adiciona pegadinhas: `requestPermission` precisa de user gesture, e há um histórico de bugs já resolvidos sobre install do SW e banner de status (ver commits recentes `fix:` em `git log -- sw.js index.html`).

## Convenções

- **Linguagem:** PT-BR em commits, comentários, UI e documentação.
- **Commits:** prefixo `fix:`/`feat:`/`chore(data):` (chore(data) é reservado pros commits automáticos do sync).
- **Versionamento do SW:** só bumpa `CACHE` quando `sw.js` muda; mudanças em `index.html` não precisam bump (network-first cuida).
