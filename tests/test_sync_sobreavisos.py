#!/usr/bin/env python3
"""Testes do sync_sobreavisos. Só stdlib: python -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import sync_sobreavisos as S  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")


def read_index():
    with open(os.path.join(REPO, "index.html"), encoding="utf-8") as fh:
        return fh.read()


class TestSerializer(unittest.TestCase):
    """O serializer tem que reproduzir o bloco de produção byte a byte."""

    def test_roundtrip_bloco_atual(self):
        original = S.extract_block(read_index())
        entries = S.parse_block(original)
        self.assertEqual(
            S.serialize(entries), original,
            "serializer divergiu do formato atual de index.html")

    def test_bloco_atual_parseia(self):
        entries = S.parse_block(S.extract_block(read_index()))
        self.assertGreater(len(entries), 100)
        self.assertTrue(all(S.KEY_RE.match(k) for k in entries))

    def test_ultima_entry_sem_virgula(self):
        out = S.serialize({"2026-03-01": {"t": "full"},
                           "2026-03-02": {"t": "full"}})
        self.assertFalse(out.rstrip().endswith(","))

    def test_mes_novo_abre_linha(self):
        out = S.serialize({"2026-03-30": {"t": "full"},
                           "2026-04-01": {"t": "full"}})
        self.assertIn('"2026-03-30":{"t":"full"},\n  "2026-04-01"', out)

    def test_tres_por_linha(self):
        entries = {"2026-03-0{}".format(i): {"t": "full"} for i in range(1, 8)}
        linhas = [l for l in S.serialize(entries).strip().split("\n")]
        self.assertEqual([l.count('"t"') for l in linhas], [3, 3, 1])


class TestHoras(unittest.TestCase):
    def test_sem_parenteses(self):
        self.assertIsNone(S.parse_hours("Arthur"))

    def test_com_parenteses(self):
        self.assertEqual(S.parse_hours("Arthur (19h-7h)"), "19h-7h")

    def test_consolida_turno_dividido(self):
        # 7h-13h + 13h-7h cobre o dia inteiro -> 7h-7h
        self.assertEqual(S.consolidate(["7h-13h", "13h-7h"]), "7h-7h")

    def test_consolida_mesma_ordem_invertida(self):
        self.assertEqual(S.consolidate(["13h-7h", "7h-13h"]), "7h-7h")

    def test_formato_inesperado_preserva_literal(self):
        self.assertEqual(S.consolidate(["manhã", "tarde"]), "manhã")


class TestNorm(unittest.TestCase):
    def test_casa_arthur_com_variacoes(self):
        for variante in ["Arthur", "ARTHUR", "  arthur  ", "Árthur",
                         "Arthur  Ayres", "arthur (19h-7h)"]:
            with self.subTest(variante=variante):
                self.assertIn("arthur", S.norm(variante))

    def test_nao_casa_outro_nome(self):
        for outro in ["Renato", "Felipe", "Roque", "Gabriel", "Dr. Paulo"]:
            with self.subTest(outro=outro):
                self.assertNotIn("arthur", S.norm(outro))


class TestParserPorCelula(unittest.TestCase):
    """Regressão do bug latente: linha P2 extra carrega 'Chefe:' nas outras colunas."""

    def test_ignora_chefe_em_linha_rotulada_p2(self):
        grid = [
            ["P1: Fernando", "P1: Gabriel"],
            ["P2: Renato (7h-19h)", "P2: Felipe"],
            ["P2: Arthur (19h-7h)", "Chefe: Arthur"],  # armadilha na coluna 1
            ["Chefe: PJ", ""],
        ]
        self.assertEqual(S.p2_entries(grid, range(0, 4), 0),
                         ["Renato (7h-19h)", "Arthur (19h-7h)"])
        # Coluna 1: só o P2 real; o 'Chefe: Arthur' NÃO pode entrar.
        self.assertEqual(S.p2_entries(grid, range(0, 4), 1), ["Felipe"])


class TestMerges(unittest.TestCase):
    def test_expande_ancora(self):
        rows = [["6", ""], ["P2: Arthur", ""]]
        merges = [{"startRowIndex": 0, "endRowIndex": 1,
                   "startColumnIndex": 0, "endColumnIndex": 2},
                  {"startRowIndex": 1, "endRowIndex": 2,
                   "startColumnIndex": 0, "endColumnIndex": 2}]
        grid = S.expand_merges(rows, merges)
        self.assertEqual(grid[0], ["6", "6"])
        self.assertEqual(grid[1], ["P2: Arthur", "P2: Arthur"])


class TestValidacao(unittest.TestCase):
    def setUp(self):
        # Volumes plausíveis: o máximo real observado num mês é 19 (Set/2026).
        self.ok = {}
        for mes in range(3, 10):
            self.ok.update({"2026-{:02d}-{:02d}".format(mes, d): {"t": "full"}
                            for d in range(1, 16)})

    def test_dict_valido_passa(self):
        self.assertEqual(S.validate(self.ok, self.ok), [])

    def test_queda_de_volume_aborta(self):
        # 105 -> 70 é queda de 33%, bem abaixo do piso de 80%.
        pequeno = dict(list(self.ok.items())[:70])
        erros = S.validate(pequeno, self.ok)
        self.assertTrue(any("queda de volume" in e for e in erros), erros)

    def test_mes_implausivel_aborta(self):
        ruim = dict(self.ok)
        ruim.update({"2026-10-{:02d}".format(d): {"t": "full"}
                     for d in range(1, 30)})
        self.assertTrue(any("implausível" in e for e in S.validate(ruim, self.ok)))

    def test_data_fora_do_escopo(self):
        ruim = dict(self.ok)
        ruim["2025-12-01"] = {"t": "full"}
        self.assertTrue(any("fora" in e for e in S.validate(ruim, self.ok)))

    def test_valor_invalido(self):
        ruim = dict(self.ok)
        ruim["2026-03-01"] = {"t": "partial"}  # sem "h"
        self.assertTrue(any("inválido" in e for e in S.validate(ruim, self.ok)))

    def test_partial_com_h_vazio_invalido(self):
        ruim = dict(self.ok)
        ruim["2026-03-01"] = {"t": "partial", "h": ""}
        self.assertTrue(any("inválido" in e for e in S.validate(ruim, self.ok)))

    def test_total_baixo_demais(self):
        erros = S.validate({"2026-03-01": {"t": "full"}}, {})
        self.assertTrue(any("60-200" in e for e in erros))


class TestGateDeSintaxe(unittest.TestCase):
    def test_rewrite_preserva_resto_do_arquivo(self):
        text = read_index()
        entries = S.parse_block(S.extract_block(text))
        novo = S.rewrite(text, entries)
        self.assertEqual(novo, text, "rewrite idempotente deveria ser no-op")

    def test_rewrite_com_mudanca(self):
        text = read_index()
        entries = dict(S.parse_block(S.extract_block(text)))
        entries["2026-03-01"] = {"t": "partial", "h": "19h-7h"}
        novo = S.rewrite(text, entries)
        self.assertEqual(S.parse_block(S.extract_block(novo)), entries)
        # Nada fora do bloco pode mudar.
        self.assertEqual(novo.split("var SOBREAVISOS")[0],
                         text.split("var SOBREAVISOS")[0])
        self.assertEqual(novo.split("\n};")[1], text.split("\n};")[1])


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sheet.json")


@unittest.skipUnless(os.path.exists(FIXTURE), "fixture ausente")
class TestGolden(unittest.TestCase):
    """O teste que prova o parser: a planilha real tem que gerar o dict real.

    A fixture é anonimizada (repo público) mas preserva tudo que o parser lê.
    Regenerar com: python scripts/sync_sobreavisos.py --dump-fixture tests/fixtures/sheet.json
    """

    def setUp(self):
        import json
        with open(FIXTURE, encoding="utf-8") as fh:
            self.grids = json.load(fh)
        del S.ANOMALIAS[:]

    def test_parser_reproduz_o_dict_de_producao(self):
        esperado = S.parse_block(S.extract_block(read_index()))
        obtido = S.build(self.grids)
        self.assertEqual(obtido, esperado)

    def test_todas_as_12_abas_presentes(self):
        self.assertEqual(sorted(self.grids), sorted(n for n, _, _ in S.TABS))

    def test_validacao_passa_na_planilha_real(self):
        novo = S.build(self.grids)
        self.assertEqual(S.validate(novo, novo), [])

    def test_fixture_nao_vaza_terceiros(self):
        with open(FIXTURE, encoding="utf-8") as fh:
            blob = fh.read()
        for nome in ["Renato", "Felipe", "Roque", "Gabriel", "Fernando",
                     "Anderson", "Paulo", "Davi"]:
            with self.subTest(nome=nome):
                self.assertNotIn(nome, blob)
        self.assertIn("Arthur", blob)

    def test_anomalia_do_parentese_e_reportada(self):
        S.build(self.grids)
        self.assertTrue(any("2027-02-14" in a for a in S.ANOMALIAS),
                        "o typo da planilha deveria ser reportado, não engolido")


class TestHorarioTorto(unittest.TestCase):
    """Regressão do bug real: célula 'P2: Arthur 7h-13h)' sem abre-parêntese.

    Exigir os dois parênteses fazia o turno parcial virar plantão cheio em
    silêncio — diria sobreaviso o dia todo num dia de 7h-13h.
    """

    def setUp(self):
        del S.ANOMALIAS[:]

    def test_parentese_faltando_ainda_parseia(self):
        self.assertEqual(S.parse_hours("Arthur 7h-13h)"), "7h-13h")

    def test_sem_parentese_nenhum(self):
        self.assertEqual(S.parse_hours("Arthur 19h-7h"), "19h-7h")

    def test_espacamento_irregular(self):
        self.assertEqual(S.parse_hours("Arthur ( 19 h - 7 h )"), "19h-7h")

    def test_formato_canonico_nao_gera_anomalia(self):
        S.parse_hours("Arthur (19h-7h)", "Jan 2026-01-01")
        self.assertEqual(S.ANOMALIAS, [])

    def test_formato_torto_gera_anomalia(self):
        S.parse_hours("Arthur 7h-13h)", "Fev 2027-02-14")
        self.assertEqual(len(S.ANOMALIAS), 1)
        self.assertIn("2027-02-14", S.ANOMALIAS[0])

    def test_sem_horario_continua_none(self):
        self.assertIsNone(S.parse_hours("Arthur"))
        self.assertEqual(S.ANOMALIAS, [])


class TestRedacao(unittest.TestCase):
    def test_preserva_arthur_e_anonimiza_o_resto(self):
        self.assertEqual(S._redact_cell("P2: Arthur (19h-7h)"), "P2: Arthur (19h-7h)")
        self.assertEqual(S._redact_cell("P2: Renato (7h-19h)"), "P2: Colega (7h-19h)")
        self.assertEqual(S._redact_cell("Chefe: Dr. Paulo"), "Chefe: Colega")

    def test_preserva_numeros_e_vazios(self):
        self.assertEqual(S._redact_cell(46082), 46082)
        self.assertEqual(S._redact_cell(""), "")
        self.assertEqual(S._redact_cell(None), None)

    def test_celula_nao_rotulada_vira_marcador_nao_vazio(self):
        # Vazio alteraria a proporção que is_date_row usa para achar a linha.
        self.assertEqual(S._redact_cell("quinta-feira"), "-")


if __name__ == "__main__":
    unittest.main(verbosity=2)
