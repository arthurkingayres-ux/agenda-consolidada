# Routine: Sync diário do dict `SOBREAVISOS`

Este arquivo contém o **prompt** da Claude Code Routine que sincroniza
o dict `SOBREAVISOS` em `index.html` com a planilha Google Sheets
`Sobreavisos CPL 2026`.

A routine roda na infra Anthropic em nuvem. **Não lê este arquivo em
tempo de execução** — o prompt efetivo está salvo na conta claude.ai
(trigger `trig_01HE517n6Ca6ot2HorZ9v2Pa`). Este arquivo é a fonte de
verdade versionada; se ajustar o prompt aqui, atualize o live com
`RemoteTrigger update` ou via `claude.ai/code/routines` → Edit.

Cadência atual: **segunda e quinta às 06:57 BRT** (cron `57 9 * * 1,4` UTC).

## Por que o prompt foi reescrito em 2026-05-25

A versão anterior dependia do conector Drive devolver o cabeçalho
`abril 2026,março '26,maio '26` no topo de cada aba para detectar o
mês. O conector parou de devolver esse header em algum momento entre
2026-05-19 e 2026-05-25, então a routine passou a falhar silenciosamente:
nenhum mês era identificado, o diff ficava vazio, e nenhum PR era aberto.
Resultado: Arthur fez uma troca na planilha em 2026-05-24 e a routine
de 2026-05-25 não a replicou no PWA. Duas mudanças críticas:

1. **Trocar a fonte de input** de `read_file_content` (markdown sem
   contexto de aba) para `download_file_content` com
   `exportMimeType=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
   parseando o XLSX com `openpyxl`. As abas têm nomes
   (`Mar, Abr, Mai, Jun, Jul, Ago, Set, Out, Nov, Dez, Jan, Fev, Escala`)
   e as células de dia são objetos `datetime` com a data completa —
   nada a inferir.
2. **Falha visível**: qualquer ABORT abre uma GitHub issue no repo,
   pra Arthur ver no email/notificação do GitHub e saber que precisa
   intervir.

## Prompt da routine

```
Você é uma routine que mantém o dict JavaScript `SOBREAVISOS` em
`index.html` sincronizado com a planilha "Sobreavisos CPL 2026". Opera
de forma autônoma, sem intervenção humana. Sempre idempotente, sempre
segura — em caso de dúvida, aborta SEM commitar e abre uma GitHub
issue (ver passo 11).

## RESTRIÇÃO DE OUTPUT (crítico)

Sua resposta textual total ao longo de toda a execução deve ter no
máximo ~500 tokens. TODO o processamento pesado (leitura da planilha,
parsing, montagem do novo dict, edição do arquivo) acontece via tool
calls (Bash, Read, Edit, Write). NUNCA ecoe na resposta textual:
(a) conteúdo binário/base64 do XLSX, (b) o dict novo ou antigo,
(c) reasoning entre passos. Entre tool calls, apenas comentários
curtos (uma linha). A única saída textual longa permitida é o resumo
final do passo 12 (≤10 linhas).

Execução prévia já estourou "32000 output token maximum" por ecoar
conteúdo. Não repita.

## Fontes
- Planilha: file_id `1-pttH9HKWt2DfoBD3wxkHkJDKE9gi7KwGjUP3I9ptUQ`
- Arquivo alvo: `index.html` na raiz do repo
- Bloco alvo: `var SOBREAVISOS = {` até `};`

## Escopo temporal
Março/2026 a Fevereiro/2027 inclusive. Ignorar datas fora.

## Abas esperadas
Mar, Abr, Mai, Jun, Jul, Ago, Set, Out, Nov, Dez, Jan, Fev. Qualquer
outra aba (ex.: `Escala`) deve ser ignorada. Mapeamento aba→ano:
Mar–Dez = 2026, Jan e Fev = 2027.

## Passos

1. Garantir Python + openpyxl disponíveis:
   `python3 -c "import openpyxl"` — se falhar,
   `pip install --quiet openpyxl`.

2. Baixar a planilha como XLSX usando a tool MCP do Google Drive
   `download_file_content` com
   `exportMimeType=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
   O retorno tem campo `content` em base64. Salvar o JSON em
   `/tmp/sheet.json` (NUNCA imprimir no chat). Em seguida, em um
   script Python (gravado em `/tmp/extract.py` e executado), decodificar
   o base64 e gravar em `/tmp/sheet.xlsx`.

3. Em `/tmp/parse.py` (escreva o script em arquivo, não inline), abrir
   `/tmp/sheet.xlsx` com `openpyxl.load_workbook(..., data_only=True)`
   e para cada aba esperada (lista acima):
   a. Caminhar pelas linhas. Identificar "blocos semanais": uma linha
      cujas células não-vazias são majoritariamente `datetime.date` ou
      `datetime.datetime` no ano-mês esperado (Mar=2026-03, …, Fev=
      2027-02). Algumas células dessa linha podem trazer datas do mês
      vizinho — IGNORAR essas (não pertencem a esta aba).
   b. As 1 a 4 linhas imediatamente abaixo são o miolo do bloco. Em
      ordem usual: linha P1, linha P2, [linha P2 EXTRA quando há
      turnos divididos], linha Chefe. Detectar por prefixo da primeira
      célula não-vazia da linha (`P1:`, `P2:`, `Chefe:`).
   c. Para cada coluna do bloco em que a linha de datas contém uma
      data DESTE mês, olhar a(s) linha(s) P2 da mesma coluna:
      - `P2: Arthur` (sem parênteses) em UMA linha → `{"t":"full"}`.
      - `P2: Arthur (HH-HH)` em UMA linha → `{"t":"partial","h":"HH-HH"}`
        (preservar o horário literal, ex.: `19h-7h`, `7h-13h`).
      - Duas linhas P2 no bloco com Arthur na mesma coluna (turnos
        divididos, ex.: `7h-13h` e `13h-7h`) → consolidar em UMA
        entry partial cobrindo do menor início ao maior fim.
      - Match em "Arthur" é case-insensitive, tolera acento e espaços
        múltiplos.
   d. Chave do dict: `YYYY-MM-DD`.

4. Ignorar aba `Escala` e qualquer aba fora da lista esperada.

5. Construir o novo dict ordenado por chave ascendente. Gravar em
   `/tmp/new_dict.json`.

6. Extrair o bloco existente do `index.html` para `/tmp/old_dict.json`
   via script Python (regex `var SOBREAVISOS = \{(.*?)\};` em modo
   DOTALL; `json.loads("{" + corpo + "}")` depois de normalizar
   vírgulas finais).

7. **VALIDAÇÕES** (qualquer falha = abortar via passo 11):
   - Todas as 12 abas esperadas foram localizadas E parseadas (mesmo
     que com 0 entries de Arthur). Se faltar aba, listar quais.
   - Total global de entries entre 60 e 200.
   - Novo total ≥ 80% do antigo (ex.: 133 → mínimo 106). Se cair
     abaixo, abortar — provavelmente o parser desalinhou.
   - Toda chave bate `^\d{4}-(0[3-9]|1[0-2]|0[12])-\d{2}$` e cai entre
     2026-03-01 e 2027-02-28 inclusive.
   - Todo value é exatamente `{"t":"full"}` ou
     `{"t":"partial","h":"<string não-vazia>"}`.
   - Nenhuma chave tem mês fora da aba de origem (ex.: data 2026-05-31
     parseada na aba Jun deve ser descartada pelo passo 3c, não chegar
     aqui).

8. Comparar `/tmp/new_dict.json` com `/tmp/old_dict.json` via `diff`.
   Se idênticos: logar "no changes" e encerrar com sucesso sem
   commitar e sem abrir issue.

9. Se diferentes, reescrever o bloco entre `var SOBREAVISOS = {` e
   `};` usando a ferramenta Edit. Formatação: ~3 entries por linha
   separadas por vírgula, indentação de 2 espaços, novo mês inicia
   nova linha. Espelhar o estilo atual.

10. Rodar `git diff --stat index.html` e conferir que SÓ `index.html`
    mudou e SÓ dentro do bloco SOBREAVISOS. Se houver mudança fora,
    `git checkout index.html` e abortar via passo 11 com
    `out-of-bounds edit`.

11. **Em caso de ABORT** (qualquer ponto acima):
    - NÃO commitar nada.
    - Antes de abrir issue nova, checar duplicatas:
      `gh issue list --state open --search "[ROUTINE FAILURE] sync-sobreavisos in:title" --json number,title`.
    - Se já existe issue aberta com o MESMO motivo (compare a primeira
      linha do motivo), apenas adicionar comentário com a data
      (`gh issue comment <num> -b "Repetiu em $(date -Iseconds)"`).
    - Senão, criar nova:
      `gh issue create --title "[ROUTINE FAILURE] sync-sobreavisos: <razão curta>" --body "<detalhes em até 10 linhas: passo que falhou, mensagem, contagem de meses/entries parseados, data ISO>"`.
    - Pular pro passo 12.

12. Integrar via PR (sandbox não permite push direto em main):
    - `git add index.html`
    - Commit na branch da sessão (criada pela sandbox; não dar
      `git checkout main`). Mensagem:
      `chore(data): sync SOBREAVISOS from sheet (<N> entries; +<A>/-<R>/~<M> vs prev)`
    - `git push -u origin HEAD`
    - `BR=$(git branch --show-current)`
    - `gh pr create --base main --head "$BR" --title "<mesma msg do commit>" --body "Routine automática (SOBREAVISOS sync). Sem revisão humana."`
    - `gh pr merge --squash --delete-branch "$BR"`
    - Se algum `gh` falhar (token sem permissão, conflito), NÃO abortar
      — o commit local já existe. Anotar em uma linha e seguir.

13. Resumo final (≤10 linhas, sem o dict, sem o XLSX):
    - Total de entries na planilha: N
    - Meses parseados: 12/12 (ou listar quais faltaram)
    - Diff por mês com mudança (ex.: `Junho 2026: +1 / -1 / ~0`)
    - Status: número do PR + `merged` / `open` / `failed:<razão>`, ou
      `no commit (no diff)`, ou `ABORTED: <razão> (issue #N)`.

## Regras invariantes
- NUNCA editar `index.html` fora do bloco SOBREAVISOS.
- NUNCA force-push.
- NUNCA criar arquivos no repo além de modificar `index.html`. Tudo
  temporário vai pra `/tmp/`.
- Se a planilha estiver inacessível, abortar via passo 11 com razão
  `sheet unreachable`.
- Se o bloco SOBREAVISOS não existir em `index.html`, abortar via
  passo 11 com `target block not found`.
- Se a aba esperada de um mês faltar ou estiver vazia, abortar via
  passo 11 com `missing tabs: <lista>` — NUNCA seguir com dict parcial.
```

## Como validar manualmente

1. Após editar o prompt aqui: cole o bloco entre as ```` ``` ```` no
   editor da routine em `claude.ai/code/routines/trig_01HE517n6Ca6ot2HorZ9v2Pa`,
   ou via `RemoteTrigger update`.
2. Clicar **Run now**; observar o session log.
3. Conferir o resultado em
   `https://github.com/arthurkingayres-ux/agenda-consolidada/pulls`
   (se houver diff) ou em
   `https://github.com/arthurkingayres-ux/agenda-consolidada/issues`
   (se abortou).
4. Abrir `https://arthurkingayres-ux.github.io/agenda-consolidada/` e
   verificar a mudança esperada.

## Troubleshooting

- **Issue aberta com `missing tabs`**: alguém renomeou/removeu uma aba
  da planilha. Renomear de volta ou ajustar a lista de abas esperadas
  no prompt.
- **Issue com `total below 80% threshold`**: indica regressão no
  parser ou planilha esvaziada. NÃO mergear "à força" — investigar.
- **Issue com `sheet unreachable`**: conector Google Drive da conta
  Anthropic desconectou. Reconectar em `claude.ai` → Settings →
  Connectors.
- **PR não foi mergeado (`failed: ...`)**: provavelmente token do
  GitHub na sandbox sem permissão de merge em branches protegidas.
  Mergear manualmente o PR pendente.
- **Routine deixou de rodar de vez**: verificar `enabled: true` em
  `RemoteTrigger get trig_01HE517n6Ca6ot2HorZ9v2Pa`. Se desabilitada,
  reativar com `RemoteTrigger update`.
