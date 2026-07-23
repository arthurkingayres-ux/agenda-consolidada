#!/usr/bin/env python3
"""Sincroniza o dict SOBREAVISOS em index.html a partir da planilha "Sobreavisos CPL".

Substitui a cloud routine que fazia o mesmo trabalho via LLM. Lê a planilha
pela Sheets API (values.batchGet) — sem openpyxl e sem round-trip de XLSX em
base64, que foi o que derrubou a routine em 2026-07-23.

Uso:
    python scripts/sync_sobreavisos.py                 # sincroniza e reescreve index.html
    python scripts/sync_sobreavisos.py --dry-run       # não escreve; imprime o diff
    python scripts/sync_sobreavisos.py --dump-fixture tests/fixtures/sheet.json
    python scripts/sync_sobreavisos.py --from-fixture tests/fixtures/sheet.json

Credenciais (env, só necessária quando busca da rede):
    GOOGLE_SERVICE_ACCOUNT_KEY = conteúdo do JSON da chave da service account

A planilha precisa estar compartilhada como Leitor com o `client_email` dessa
chave. Só `--from-fixture` e os testes rodam sem credencial e sem dependência.

Sai com 0 em sucesso (com ou sem mudança) e 1 em qualquer abort. A mensagem
de erro na stderr é o que vira corpo da issue no GitHub Actions.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

SPREADSHEET_ID = os.environ.get(
    "SOBREAVISOS_SHEET_ID", "1-pttH9HKWt2DfoBD3wxkHkJDKE9gi7KwGjUP3I9ptUQ"
)

# Aba -> (ano, mês). Mar–Dez = 2026, Jan e Fev = 2027.
TABS = [
    ("Mar", 2026, 3), ("Abr", 2026, 4), ("Mai", 2026, 5), ("Jun", 2026, 6),
    ("Jul", 2026, 7), ("Ago", 2026, 8), ("Set", 2026, 9), ("Out", 2026, 10),
    ("Nov", 2026, 11), ("Dez", 2026, 12), ("Jan", 2027, 1), ("Fev", 2027, 2),
]

TARGET = "index.html"
BLOCK_RE = re.compile(r"(var SOBREAVISOS = \{)(.*?)(\n\};)", re.DOTALL)

# Epoch do Google Sheets: serial 1 == 1899-12-31.
SHEETS_EPOCH = date(1899, 12, 30)

# Rótulo de célula: "P1: Fernando", "P2: Arthur (19h-7h)", "Chefe: Dr. Davi".
CELL_RE = re.compile(r"^\s*(P1|P2|Chefe)\s*:\s*(.*)$", re.IGNORECASE)
# Casa o intervalo em qualquer lugar do texto, com ou sem parênteses. A planilha
# tem células com parêntese faltando ("Arthur 7h-13h)"); exigir os dois fazia o
# turno virar plantão cheio silenciosamente. Ver ANOMALIAS.
TIME_RE = re.compile(r"(\d{1,2})\s*h\s*-\s*(\d{1,2})\s*h", re.IGNORECASE)
WELL_FORMED_RE = re.compile(r"\(\s*\d{1,2}\s*h\s*-\s*\d{1,2}\s*h\s*\)", re.IGNORECASE)
RANGE_RE = re.compile(r"^\s*(\d{1,2})\s*h\s*-\s*(\d{1,2})\s*h\s*$", re.IGNORECASE)

# Células com formato torto que o parser tolerou. Não falham o sync, mas são
# reportadas para você poder pedir a correção na planilha.
ANOMALIAS = []

MIN_DATE, MAX_DATE = date(2026, 3, 1), date(2027, 2, 28)
KEY_RE = re.compile(r"^\d{4}-(0[3-9]|1[0-2]|0[12])-\d{2}$")


class Abort(Exception):
    """Falha que deve parar o sync sem tocar em index.html."""


# --------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------

def norm(text):
    """Minúsculas, sem acento, espaços colapsados. Para casar 'Arthur'."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def serial_to_date(value):
    """Converte serial do Sheets em date. Devolve None se não for data plausível."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    n = int(value)
    # Serial de datas reais nesta planilha fica na casa dos 46000 (2026).
    if not 1 <= n <= 100000:
        return None
    try:
        return SHEETS_EPOCH + timedelta(days=n)
    except OverflowError:
        return None


# --------------------------------------------------------------------------
# Busca (rede)
# --------------------------------------------------------------------------

def _get_json(url, token):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        if exc.code in (403, 404):
            raise Abort(
                "Sheets API HTTP {}: a planilha não está acessível pela service "
                "account. Confirme que ela foi compartilhada (Leitor) com o "
                "client_email da chave.\n{}".format(exc.code, body))
        raise Abort("Sheets API HTTP {}: {}".format(exc.code, body))
    except urllib.error.URLError as exc:
        raise Abort("Sheets API inacessível: {}".format(exc.reason))


SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


def access_token():
    """Token de acesso a partir da chave da service account.

    Usa service account em vez de OAuth de usuário porque não há consent
    screen, nada expira e não existe client secret pra gerenciar. A planilha
    precisa estar compartilhada (Leitor) com o client_email da chave.

    `google-auth` é a única dependência do projeto: assinar o JWT exige
    RSA-SHA256, que a stdlib não faz. Import tardio pra manter os testes
    rodando sem instalar nada.
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not raw:
        raise Abort("GOOGLE_SERVICE_ACCOUNT_KEY ausente (JSON da chave da "
                    "service account)")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Abort("GOOGLE_SERVICE_ACCOUNT_KEY não é JSON válido: {}".format(exc))

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        raise Abort("dependência ausente: pip install google-auth requests")

    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[SCOPE])
        creds.refresh(Request())
    except Exception as exc:  # google-auth levanta tipos variados
        raise Abort("falha ao autenticar a service account: {}".format(exc))
    return creds.token


def fetch_sheet():
    """Busca valores + merges. Devolve {aba: grid} com merges já expandidos."""
    token = access_token()
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + SPREADSHEET_ID

    meta = _get_json(base + "?" + urllib.parse.urlencode({
        "fields": "sheets(properties(title,sheetId),merges)"}), token)

    params = [("valueRenderOption", "UNFORMATTED_VALUE"),
              ("dateTimeRenderOption", "SERIAL_NUMBER")]
    params += [("ranges", name) for name, _, _ in TABS]
    values = _get_json(base + "/values:batchGet?" + urllib.parse.urlencode(params), token)

    merges_by_tab = {}
    for sheet in meta.get("sheets", []):
        title = sheet.get("properties", {}).get("title", "")
        merges_by_tab[title] = sheet.get("merges", [])

    grids = {}
    for (name, _, _), vr in zip(TABS, values.get("valueRanges", [])):
        grids[name] = expand_merges(vr.get("values", []), merges_by_tab.get(name, []))
    return grids


def expand_merges(rows, merges):
    """Replica o valor da célula-âncora por todo o range mesclado.

    O values.batchGet só preenche a âncora de um merge; as demais vêm vazias.
    Sem isso, uma data mesclada e o P2 correspondente podem não se alinhar.
    """
    grid = [list(r) for r in rows]
    for m in merges:
        r0, r1 = m.get("startRowIndex", 0), m.get("endRowIndex", 0)
        c0, c1 = m.get("startColumnIndex", 0), m.get("endColumnIndex", 0)
        if r0 >= len(grid):
            continue
        anchor = cell(grid, r0, c0)
        if anchor in (None, ""):
            continue
        for r in range(r0, min(r1, len(grid))):
            for c in range(c0, c1):
                while len(grid[r]) <= c:
                    grid[r].append("")
                grid[r][c] = anchor
    return grid


def redact(grids):
    """Anonimiza a grade para virar fixture de teste.

    O repositório é público e a planilha do CPL traz nome e escala de todos os
    plantonistas. Preserva exatamente o que o parser lê — posições, mesclagens,
    rótulos P1/P2/Chefe, horários e as células do Arthur — e troca o resto por
    marcadores. Células não-rotuladas viram '-' em vez de vazio para não alterar
    a proporção de células preenchidas de que `is_date_row` depende.
    """
    out = {}
    for tab, grid in grids.items():
        out[tab] = [[_redact_cell(v) for v in row] for row in grid]
    return out


def _redact_cell(value):
    if value is None or value == "" or not isinstance(value, str):
        return value  # números (datas) passam intactos
    m = CELL_RE.match(value)
    if not m:
        return "-"
    role, rest = m.group(1), m.group(2)
    if "arthur" in norm(rest):
        return value  # única pessoa cujos dados são realmente nossos
    hours = TIME_RE.search(rest)
    sufixo = " ({}h-{}h)".format(hours.group(1), hours.group(2)) if hours else ""
    return "{}: Colega{}".format(role, sufixo)


def cell(grid, r, c):
    if 0 <= r < len(grid) and 0 <= c < len(grid[r]):
        return grid[r][c]
    return ""


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def date_columns(grid, row, year, month):
    """Colunas da linha que contêm uma data DESTE ano-mês. Ignora mês vizinho."""
    found = {}
    for c, value in enumerate(grid[row]):
        d = serial_to_date(value)
        if d and d.year == year and d.month == month:
            found[c] = d
    return found


def is_date_row(grid, row, year, month):
    """Linha é 'linha de datas' se a maioria das células não-vazias são datas."""
    non_empty = [v for v in grid[row] if v not in (None, "")]
    if len(non_empty) < 3:
        return False
    dates = [v for v in non_empty if serial_to_date(v) is not None]
    if len(dates) < len(non_empty) / 2:
        return False
    # Precisa ter ao menos uma data do mês esperado (senão é grade de outro mês).
    return bool(date_columns(grid, row, year, month))


def p2_entries(grid, rows, col):
    """Células rotuladas P2 na coluna, dentro do bloco. Devolve lista de nomes."""
    out = []
    for r in rows:
        raw = cell(grid, r, col)
        if raw in (None, ""):
            continue
        m = CELL_RE.match(str(raw))
        # Classificação POR CÉLULA, não por linha: quando há turno dividido a
        # planilha insere uma linha P2 extra que, nas outras colunas, carrega o
        # 'Chefe:' daquele dia. Classificar a linha inteira leria chefe como P2.
        if m and m.group(1).upper() == "P2":
            out.append(m.group(2).strip())
    return out


def parse_hours(label, onde=""):
    """'Arthur (19h-7h)' -> '19h-7h'. Sem intervalo de horas -> None.

    Tolera parêntese faltando/ausente e espaçamento irregular, mas registra a
    célula em ANOMALIAS quando o formato não é o canônico '(HHh-HHh)'.
    """
    m = TIME_RE.search(label)
    if not m:
        return None
    if not WELL_FORMED_RE.search(label):
        ANOMALIAS.append("{}: {!r} — formato de horário torto, "
                         "interpretado como {}h-{}h".format(
                             onde, label.strip(), m.group(1), m.group(2)))
    return "{}h-{}h".format(int(m.group(1)), int(m.group(2)))


def consolidate(hours_list):
    """Une turnos divididos: do menor início ao maior fim (fim que vira o dia soma 24)."""
    parsed = []
    for h in hours_list:
        m = RANGE_RE.match(h)
        if not m:
            return hours_list[0]  # formato inesperado: preserva literal do primeiro
        start, end = int(m.group(1)), int(m.group(2))
        if end <= start:
            end += 24
        parsed.append((start, end))
    start = min(p[0] for p in parsed)
    end = max(p[1] for p in parsed)
    return "{}h-{}h".format(start, end % 24)


def parse_tab(grid, year, month, tab):
    """Extrai {YYYY-MM-DD: entry} das escalas do Arthur numa aba."""
    result = {}
    date_rows = [r for r in range(len(grid)) if is_date_row(grid, r, year, month)]
    if not date_rows:
        raise Abort("aba {}: nenhuma linha de datas reconhecida".format(tab))

    for idx, row in enumerate(date_rows):
        # Corpo do bloco: linhas até a próxima linha de datas (teto de 6).
        stop = date_rows[idx + 1] if idx + 1 < len(date_rows) else len(grid)
        body = range(row + 1, min(stop, row + 7))

        for col, day in date_columns(grid, row, year, month).items():
            labels = [l for l in p2_entries(grid, body, col)
                      if "arthur" in norm(l)]
            if not labels:
                continue
            onde = "{} {}".format(tab, day.isoformat())
            hours = [h for h in (parse_hours(l, onde) for l in labels) if h]
            if not hours:
                entry = {"t": "full"}
            elif len(hours) == 1:
                entry = {"t": "partial", "h": hours[0]}
            else:
                entry = {"t": "partial", "h": consolidate(hours)}

            key = day.isoformat()
            prev = result.get(key)
            if prev is not None and prev != entry:
                raise Abort(
                    "aba {}: {} aparece com escalas conflitantes ({} vs {})"
                    .format(tab, key, prev, entry))
            result[key] = entry
    return result


def build(grids):
    del ANOMALIAS[:]
    total = {}
    for name, year, month in TABS:
        if name not in grids:
            raise Abort("aba ausente na resposta da planilha: {}".format(name))
        for key, entry in parse_tab(grids[name], year, month, name).items():
            total[key] = entry
    return dict(sorted(total.items()))


# --------------------------------------------------------------------------
# Validação (portada verbatim dos passos 7 e 10 do prompt da routine)
# --------------------------------------------------------------------------

def validate(new, old):
    errors = []

    if not 60 <= len(new) <= 200:
        errors.append("total fora da faixa 60-200: {}".format(len(new)))

    if old and len(new) < 0.8 * len(old):
        errors.append("queda de volume: {} entries vs {} anteriores (<80%) — "
                      "provável desalinhamento do parser".format(len(new), len(old)))

    for key, entry in new.items():
        if not KEY_RE.match(key):
            errors.append("chave fora do padrão: {!r}".format(key))
            continue
        d = date.fromisoformat(key)
        if not MIN_DATE <= d <= MAX_DATE:
            errors.append("data fora do escopo Mar/2026-Fev/2027: {}".format(key))
        if entry == {"t": "full"}:
            continue
        if (entry.get("t") == "partial" and isinstance(entry.get("h"), str)
                and entry["h"] and set(entry) == {"t", "h"}):
            continue
        errors.append("valor inválido em {}: {!r}".format(key, entry))

    per_month = {}
    for key in new:
        per_month[key[:7]] = per_month.get(key[:7], 0) + 1
    for ym, count in sorted(per_month.items()):
        # Faixa larga e determinística: não existe julgamento a ser burlado aqui.
        if count > 25:
            errors.append("{}: {} entries (>25, implausível)".format(ym, count))

    return errors


# --------------------------------------------------------------------------
# Serialização
# --------------------------------------------------------------------------

def serialize(entries):
    """Reproduz o formato do bloco: 3 entries por linha, mês novo abre linha.

    Constrói juntando tudo com ',' e só depois quebra em linhas — nunca insere
    vírgula "por linha" à mão. Foi exatamente esse erro manual que gerou o
    SyntaxError de 2026-06-01 e deixou o PWA sem abrir.
    """
    lines, chunk, current_month = [], [], None
    for key, entry in sorted(entries.items()):
        month = key[:7]
        if month != current_month and chunk:
            lines.append(chunk)
            chunk = []
        current_month = month
        chunk.append('"{}":{}'.format(key, json.dumps(entry, separators=(",", ":"))))
        if len(chunk) == 3:
            lines.append(chunk)
            chunk = []
    if chunk:
        lines.append(chunk)

    # O grupo de fechamento da regex já carrega o "\n};", então o bloco
    # termina na última entry — sem newline sobrando.
    body = ",\n  ".join(",".join(line) for line in lines)
    return "\n  " + body


def extract_block(text):
    m = BLOCK_RE.search(text)
    if not m:
        raise Abort("bloco 'var SOBREAVISOS = {' não encontrado em " + TARGET)
    return m.group(2)


def parse_block(body):
    stripped = body.strip().rstrip(",")
    try:
        return json.loads("{" + stripped + "}")
    except json.JSONDecodeError as exc:
        raise Abort("bloco SOBREAVISOS atual não é JSON parseável: {}".format(exc))


def rewrite(text, entries):
    new_text = BLOCK_RE.sub(
        lambda m: m.group(1) + serialize(entries) + m.group(3), text, count=1)

    # GATE DE SINTAXE: reparseia o que acabou de ser escrito. Este gate teria
    # pego o incidente de 2026-06-01. Não remover.
    roundtrip = parse_block(extract_block(new_text))
    if roundtrip != entries:
        raise Abort("serialização produziu JS inválido ou divergente do dict")
    return new_text


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def diff_summary(new, old):
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(new) & set(old) if new[k] != old[k])
    return added, removed, changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="não escreve index.html; só relata o diff")
    ap.add_argument("--dump-fixture", metavar="PATH",
                    help="salva a grade como fixture de teste (anonimizada) e sai")
    ap.add_argument("--no-redact", action="store_true",
                    help="NÃO anonimiza o dump. O repo é público — não commite isso.")
    ap.add_argument("--from-fixture", metavar="PATH",
                    help="lê a grade de um arquivo em vez da rede")
    args = ap.parse_args(argv)

    try:
        if args.from_fixture:
            with open(args.from_fixture, encoding="utf-8") as fh:
                grids = json.load(fh)
        else:
            grids = fetch_sheet()

        if args.dump_fixture:
            saida = grids if args.no_redact else redact(grids)
            with open(args.dump_fixture, "w", encoding="utf-8") as fh:
                json.dump(saida, fh, ensure_ascii=False, indent=1, sort_keys=True)
            print("fixture salva em {} ({})".format(
                args.dump_fixture,
                "CRUA — contém dados de terceiros, não commitar"
                if args.no_redact else "anonimizada"))
            return 0

        with open(TARGET, encoding="utf-8") as fh:
            text = fh.read()
        old = parse_block(extract_block(text))

        new = build(grids)
        errors = validate(new, old)
        if errors:
            raise Abort("validação falhou:\n- " + "\n- ".join(errors))

        for aviso in ANOMALIAS:
            print("AVISO {}".format(aviso))

        added, removed, changed = diff_summary(new, old)
        if not (added or removed or changed):
            print("no changes ({} entries)".format(len(new)))
            return 0

        summary = "{} entries; +{}/-{}/~{} vs prev".format(
            len(new), len(added), len(removed), len(changed))
        for label, keys in (("+", added), ("-", removed), ("~", changed)):
            for key in keys:
                print("  {} {}".format(label, key))

        if args.dry_run:
            print("[dry-run] " + summary)
            return 0

        with open(TARGET, "w", encoding="utf-8", newline="") as fh:
            fh.write(rewrite(text, new))
        print(summary)
        return 0

    except Abort as exc:
        print("ABORTED: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
