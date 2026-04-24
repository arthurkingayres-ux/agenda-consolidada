# Routine: Sync diário do dict `SOBREAVISOS`

Este arquivo contém o **prompt** da Claude Code Routine que sincroniza diariamente
o dict `SOBREAVISOS` em `index.html` com a planilha Google Sheets
`Sobreavisos CPL 2026`.

A routine roda na infra Anthropic em nuvem. Não usa este arquivo em tempo de
execução — o prompt efetivo está salvo na conta claude.ai. Este arquivo serve
como fonte de verdade versionada; se ajustar o prompt aqui, cole o novo em
`/schedule update` ou em `claude.ai/code/routines` → Edit.

## Setup (uma vez só)

1. Conectar o repo no Claude Code Web (se ainda não conectou):
   - Na CLI (dentro deste repo): `/web-setup`
   - Ou web: `claude.ai/code` → Connect GitHub → selecionar `arthurkingayres-ux/agenda-consolidada`
2. Garantir que os conectores **Google Drive** e **Google Calendar** estão
   vinculados em `claude.ai` → Settings → Connectors (já estão para este
   usuário).
3. Registrar a routine:
   - CLI rápida: `/schedule daily at 06:57 BRT, sync SOBREAVISOS from sheet`
     → Claude perguntará prompt, repo, ambiente; cole o prompt abaixo.
   - OU via web: `claude.ai/code/routines` → New routine → colar prompt
     abaixo, repo = `arthurkingayres-ux/agenda-consolidada`, trigger = Schedule
     diário 06:57 BRT, environment = Default, connectors = Google Drive +
     Google Calendar (Drive é o mínimo; Calendar fica por redundância).
4. **Importante**: na configuração do repo, marcar
   **Allow unrestricted branch pushes** (senão a routine só consegue pushar
   em `claude/*` e não atualiza `main`).

## Prompt da routine

```
Você é uma routine que mantém o dict JavaScript `SOBREAVISOS` em `index.html`
sincronizado com a planilha "Sobreavisos CPL 2026". Opera de forma autônoma,
sem intervenção humana. Sempre idempotente, sempre segura — em caso de dúvida,
aborta sem commitar.

## RESTRIÇÃO DE OUTPUT (crítico, não negociável)

Sua resposta textual total ao longo de toda a execução deve ter no máximo
~500 tokens. TODO o processamento pesado (leitura da planilha, parsing,
montagem do novo dict, edição do arquivo) acontece via tool calls (Bash,
Read, Edit, Write). NUNCA ecoe na resposta textual: (a) CSV ou conteúdo da
planilha, (b) o dict novo ou antigo, (c) reasoning "mostrando trabalho"
entre passos. Entre tool calls, apenas comentários curtos (uma linha). A
ÚNICA saída textual longa permitida é o resumo final do passo 10
(≤10 linhas).

Execução anterior falhou com "API Error: response exceeded 32000 output
token maximum" exatamente por ecoar CSV/dict inline. Não repita.

## Fontes
- Planilha Google Sheets: "Sobreavisos CPL 2026"
  (file_id: 1-pttH9HKWt2DfoBD3wxkHkJDKE9gi7KwGjUP3I9ptUQ)
- Arquivo alvo: `index.html` na raiz deste repo
- Bloco alvo: `var SOBREAVISOS = {` até `};` (hoje linhas ~151 a ~190)

## Escopo temporal
Março/2026 a Fevereiro/2027 inclusive. Ignorar meses fora desse intervalo.

## Passos

1. Ler a planilha via conector Google Drive (`read_file_content`). O retorno é
   CSV por aba; cada aba representa UM mês. Salve o CSV em `/tmp/sheet.csv`
   em vez de colocar inline na resposta.

2. Para cada aba mensal no escopo, parseie com um script Python ou awk via
   Bash (escreva o script em arquivo e execute — não cole a saída completa
   no chat):

   a. Detectar o mês/ano pelo cabeçalho tipo
      `<nome-do-mês> <ano>,<mini-mês anterior>,<mini-mês seguinte>`
      (ex.: `abril 2026,março '26,maio '26`). Mapear nome→número em
      português (janeiro=1 … dezembro=12).

   b. Percorrer as semanas. Cada semana tem:
      - linha de números de dia (primeiras 7 colunas; células vazias
        representam dias do mês vizinho e devem ser ignoradas);
      - linha `P1: <nome>,...` (ignorar);
      - linha `P2: <nome>,...`  ← fonte dos sobreavisos;
      - linha `Chefe: <nome>,...` (ignorar);
      - ATENÇÃO: quando um dia é dividido por horário (ex.: plantão
        7h-19h cai num residente e 19h-7h em outro), o sheet cria uma
        LINHA EXTRA entre `P2:` e `Chefe:` contendo o segundo turno.
        Tratar essa linha extra como parte do mesmo dia.

   c. Para cada célula `P2` que contenha "Arthur" (case-insensitive,
      tolerar espaços múltiplos e acentos):
      - sem parentheses → `{"t":"full"}`
      - com parentheses contendo horário → `{"t":"partial","h":"<horário>"}`
        Ex.: `P2: Arthur (19h-7h)` → `{"t":"partial","h":"19h-7h"}`
      - se houver duas cédulas "Arthur" no mesmo dia (turnos divididos,
        ex.: 7h-13h + 13h-7h), consolidar em UMA entry partial cobrindo
        o intervalo combinado (menor início → maior fim).

   d. Chave no dict resultante: `YYYY-MM-DD` com zero-padding.

3. Construir o novo dict ordenado por chave ascendente. Grave em
   `/tmp/new_dict.json`.

4. Extrair o bloco existente de `SOBREAVISOS` do `index.html` em
   `/tmp/old_dict.json` via script.

5. **Validações** (aborta imediatamente se qualquer uma falhar):

   - Cada mês no escopo tem entre 3 e 14 entries. Se algum mês tiver 0 ou
     >14, abortar.
   - Total global entre 60 e 200 entries.
   - O novo total não pode ser menor que 80% do total antigo.
   - Toda chave matches `^\d{4}-(0[3-9]|1[0-2]|0[12])-\d{2}$` e está
     dentro do escopo Mar/2026 – Fev/2027.
   - Todo value é exatamente `{"t":"full"}` ou
     `{"t":"partial","h":"<string não-vazia>"}`.

   Em caso de abort, logar a razão completa e encerrar SEM tocar o arquivo.

6. Comparar novo vs. antigo. Se idênticos: logar "no changes" e encerrar
   sem commitar.

7. Se diferentes: reescrever o bloco inteiro entre `var SOBREAVISOS = {` e
   `};`. Formatação: uma entry por linha NÃO; agrupar ~3 entries por
   linha separadas por vírgula, indentação de 2 espaços, cada novo mês
   começando em linha nova. Espelhar o estilo atual.

8. Rodar `git diff index.html` e conferir que APENAS o bloco
   `SOBREAVISOS` mudou. Se houver mudança fora desse bloco, abortar e
   reverter.

9. Commit em `main`:
   - Mensagem: `chore(data): sync SOBREAVISOS from sheet (<N> entries; +<A>/-<R> vs prev)`
   - Autor: identidade do GitHub conectado (default).
   - Push direto em `main`.

10. Resumo final (sempre imprimir, mesmo em no-op):
    - Total de entries lido da planilha.
    - Diff por mês: `Abril 2026: +2 / -1 / =5`.
    - Commit SHA, ou "no commit (no diff)", ou "ABORTED: <razão>".

## Regras
- NUNCA editar outras partes do `index.html` fora do bloco `SOBREAVISOS`.
- NUNCA fazer force-push.
- NUNCA criar um arquivo ou branch além do necessário.
- Se a planilha estiver inacessível ou vazia, abortar com
  `ABORTED: sheet unreachable` e não commitar nada.
- Se o `index.html` não tiver o bloco `SOBREAVISOS` esperado, abortar com
  `ABORTED: target block not found`.
```

## Como validar manualmente

1. Após criar a routine, clicar **Run now** em `claude.ai/code/routines` e
   observar o session log.
2. Conferir o commit em
   `https://github.com/arthurkingayres-ux/agenda-consolidada/commits/main`.
3. Abrir `https://arthurkingayres-ux.github.io/agenda-consolidada/` e ver se
   um sobreaviso recém-adicionado aparece.

## Troubleshooting

- **Routine pushou em `claude/sync-sobreavisos` e não em `main`**: marcar
  *Allow unrestricted branch pushes* no repo da routine.
- **"sheet unreachable"**: conector Google Drive pode ter desconectado.
  Reconectar em `claude.ai` → Settings → Connectors.
- **Commits diários repetidos sem diff real**: bug no diff check do
  prompt; ajustar e `/schedule update`.
- **Parser desalinhou por mudança de layout da planilha**: a validação
  por faixa de entries/mês deve pegar; o commit não sai e a routine
  reporta ABORTED. Ajustar o prompt e atualizar.
