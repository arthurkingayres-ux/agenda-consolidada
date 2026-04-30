# Contagem de plantões ponderada por duração

**Data:** 2026-04-30
**Status:** Aprovado para implementação
**Arquivo afetado:** `index.html`

## Problema

Hoje o cabeçalho do mês e o card "Produção HVC" contam **eventos brutos** (1 evento = 1 plantão). Isso ignora que plantões têm durações diferentes:

- Plantão noturno padrão: 12h (ex.: 19h-07h) → 1 plantão completo
- Plantão diurno parcial: 6h (ex.: 07h-13h ou 13h-19h) → meio plantão
- Plantão estendido: 24h → 2 plantões

Exemplo de Maio/2026 (verificado contra o Google Calendar):

| Data | Horário | Duração | Peso correto |
|------|---------|---------|--------------|
| 9/mai | 07h-13h | 6h | 0,5 |
| 9/mai | 13h-19h | 6h | 0,5 |
| 10/mai | 13h-19h | 6h | 0,5 |
| 10/mai | 19h-07h+1 | 12h | 1,0 |
| 12/mai | 19h-07h+1 | 12h | 1,0 |
| 15/mai | 19h-07h+1 | 12h | 1,0 |
| 26/mai | 19h-07h+1 | 12h | 1,0 |

Soma correta: **5,5 plantões**. Dashboard exibe: **7 plt** (errado).

A taxa atual também está desatualizada: código usa R$ 1.600/plantão, valor real é **R$ 1.700/plantão**.

## Regra de cálculo

Peso de cada evento = `(end - start) / 12 horas`, calculado em milissegundos para robustez contra virada de meia-noite:

```
weight = (en.getTime() - st.getTime()) / (1000 * 60 * 60 * 12)
```

Casos cobertos:
- 6h → 0,5
- 12h → 1,0
- 18h → 1,5
- 24h → 2,0

Quando há múltiplos eventos no mesmo dia, somam-se os pesos individuais. O peso total do mês é a soma de todos os pesos diários.

## Mudanças no `index.html`

### 1. Estrutura `HVC[key]`

Adicionar campo `weight` (número, soma dos pesos dos eventos do dia). Manter `eventCount` para o label "HVC (múltiplos)" e o detalhe "N turnos neste dia".

### 2. Ingestão de eventos reais

Em [index.html:316-339](../../../index.html#L316-L339), no `events.forEach`:

- Calcular `w = (en - st) / (1000 * 3600 * 12)` para cada evento.
- Se `HVC[key]` já existe: `HVC[key].weight += w; HVC[key].eventCount += 1;`
- Senão: `HVC[key] = { ..., eventCount: 1, weight: w };`

### 3. Ingestão de projeções

Em [index.html:343-359](../../../index.html#L343-L359), cada slot ganha peso explícito:

- `HVC Noturno` (19h-07h, 12h) → `weight: 1.0`
- `HVC Diurno` (07h-19h, 12h) → `weight: 1.0`
- `HVC Tarde+Noturno` (13h-07h, 18h) → `weight: 1.5`

### 4. Helper de formatação

Adicionar função `fmtPlt(n)`:

```js
function fmtPlt(n) {
  return n % 1 === 0 ? String(n) : n.toFixed(1).replace('.', ',');
}
```

Decimal só quando há fração; vírgula como separador (pt-BR).

### 5. Cabeçalho do mês

Em [index.html:466-471](../../../index.html#L466-L471):

- Substituir `hc`/`ec` por `wt` (peso total do mês), somando `HVC[k].weight`.
- Eliminar o branch `isR ? ec : hc` — ambos agora usam `wt`.
- Exibir como `'✓ ' + fmtPlt(wt) + ' plt'` (real) ou `'⏳ ' + fmtPlt(wt) + ' plt'` (projeção).

### 6. Card de Produção HVC

Em [index.html:442-452](../../../index.html#L442-L452):

- Texto: `R$ 1.700/plantão` (atualizar de R$ 1.600).
- Loop: substituir `cnt += eventCount` por `wt += weight`.
- Cálculo: `amt = wt * 1700` (ajustar de `cnt * 1600`).
- Exibição: `<div class="sc">' + fmtPlt(wt) + ' plt</div>`.

### 7. Detalhe do dia

Em [index.html:538-541](../../../index.html#L538-L541):

- Substituir o texto "N turnos neste dia" por `fmtPlt(weight) + ' plantões (N turnos)'` quando `eventCount > 1`.
- Mantém a informação útil de quantidade de turnos físicos, mas adiciona o peso ponderado.

## Não muda

- Detecção de "mês real" (`realMonths[ymK]`) — continua marcando o mês inteiro como real se houver ≥ 1 evento naquele mês.
- Lógica de conflito Sobreaviso × HVC — independe do peso.
- Cores e ícones do grid — indicam presença, não quantidade.
- Filtros, navegação, autenticação OAuth.

## Testes manuais

Após implementação, abrir o PWA logado e verificar:

1. **Maio/2026**: cabeçalho mostra `✓ 5,5 plt`; card produção mostra `5,5 plt` e `R$ 9.350`.
2. **Abril/2026**: recalcular manualmente os eventos do mês, confirmar que peso total bate com o cabeçalho.
3. **Meses de projeção** (set/26 em diante): cada mês deve mostrar peso correto baseado nos slots projetados (5 plantões noturnos + 0 ou 1 tarde+noturno). Atualmente mostra 6 plt — após o fix pode mostrar `6,5 plt` se a semana cair em padrão que inclui o slot de 18h.
4. **Total de produção**: somar os `amt` de todos os meses deve bater com o "Total: R$ X" exibido.
5. **Dia com plantão único de 6h**: detalhe do dia deve mostrar "0,5 plantão".
6. **Dia com múltiplos turnos** (ex.: 9/mai, 10/mai): detalhe deve mostrar peso somado + N turnos.

## Fora de escopo

- Investigação de "evento fantasma" — confirmado que não existe; os 7 eventos de maio são todos legítimos.
- Mudança no cálculo de "mês real" para considerar percentual preenchido — a presença de qualquer evento real continua marcando o mês como ✓.
- Botão de diagnóstico para dump de eventos — não foi necessário; investigação foi feita via console na sessão de brainstorming.
- Configuração da taxa por plantão como variável (ex.: localStorage) — fica hardcoded em R$ 1.700 até nova mudança.
