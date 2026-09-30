# Consultas ao Alfred

Regime leve (sem camada de projeto). Uma linha por consulta discricionária.

- 2026-09-30 — sync SOBREAVISOS quebrado desde 03/08 (golden acoplado ao index.html vivo) + workflow desativado por inatividade. Recomendação: expected.json derivado da fixture commitada (não re-dumpar a planilha), keepalive feito à mão no próprio workflow, retrospectiva das datas de ago–set erradas para Arthur. Maior gravidade: material. Sem veto, sem escalação. `camada_de_projeto: null` (esperado — regime leve). Verificador: `OK — 1 invocação(ões) auditada(s), todas em claude-fable-5 por evidência do servidor.`
- 2026-09-30 — design do indicador de última sincronização no PWA (fonte: API pública do GitHub Actions). Recomendação: manter a API como fonte; excluir api.github.com do SW (senão resposta velha offline gera alarme falso) com bump v9; duas consultas filtradas (`status=completed` / `status=success`, `per_page=1`); alarmar só em failure/timed_out/startup_failure; tratar !ok (403) como falha de consulta. Maior gravidade: material. Sem veto, sem escalação. Verificador: `OK - 3 invocação(ões) auditada(s), todas em claude-fable-5 por evidência do servidor.`
