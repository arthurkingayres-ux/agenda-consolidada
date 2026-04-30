# Contagem de plantões ponderada — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar contagem por evento (1 evento = 1 plantão) por contagem ponderada por duração (peso = horas/12) no cabeçalho mensal e no card de produção; atualizar taxa para R$ 1.700/plantão.

**Architecture:** Mudança localizada em `index.html`. Adicionar campo `weight` em cada entrada `HVC[key]`, computado a partir da diferença `end - start` em milissegundos. Substituir `eventCount`/`hc`/`ec` nos consumidores por soma de `weight`. Adicionar helper de formatação `fmtPlt` para exibir decimal só quando há fração.

**Tech Stack:** HTML/JS vanilla, sem framework de testes. Verificação manual via Playwright contra dados reais do Google Calendar do usuário (Maio/2026 como caso de referência: deve mostrar 5,5 plt e R$ 9.350).

**Spec:** [docs/superpowers/specs/2026-04-30-contagem-plantoes-ponderada-design.md](../specs/2026-04-30-contagem-plantoes-ponderada-design.md)

**Server local:** `http://127.0.0.1:8765/index.html` não autoriza Google OAuth (origin_mismatch). Verificação acontece em produção: `https://arthurkingayres-ux.github.io/agenda-consolidada/` com push pra `main`.

---

## File Structure

Único arquivo afetado: `index.html`.

Pontos de mudança (números de linha do estado atual antes da implementação):

| Local | Linhas | Responsabilidade |
|-------|--------|------------------|
| Helpers utilitários | após 222 | Adicionar `fmtPlt(n)` |
| Ingestão eventos reais | 316-339 | Calcular `weight` por evento e somar no dia |
| Ingestão projeções | 343-359 | Atribuir `weight` explícito por slot |
| Cabeçalho mensal | 466-471 | Somar `weight` em vez de contar dias/eventos |
| Card produção | 442-452 | Somar `weight`, taxa R$ 1.700, exibir `fmtPlt` |
| Detalhe do dia | 538-541 | Mostrar peso ponderado quando múltiplos turnos |

---

## Task 1: Adicionar helper `fmtPlt`

**Files:**
- Modify: `index.html` (adicionar logo após linha 224, junto dos outros helpers globais)

- [ ] **Step 1: Adicionar a função**

Inserir entre `function todayK()` e `var HVC = {};`:

```js
function fmtPlt(n) {
  if (n % 1 === 0) return String(n);
  return n.toFixed(1).replace('.', ',');
}
```

- [ ] **Step 2: Verificar no console do navegador**

Abrir `https://arthurkingayres-ux.github.io/agenda-consolidada/`, abrir DevTools (ou Playwright `browser_evaluate`), rodar:

```js
[fmtPlt(0.5), fmtPlt(1), fmtPlt(5.5), fmtPlt(6), fmtPlt(1.5)]
```

Expected: `["0,5", "1", "5,5", "6", "1,5"]`

(Esse passo só é executável depois do push; pular se ainda local.)

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: add fmtPlt helper for plantão count formatting"
```

---

## Task 2: Calcular `weight` na ingestão de eventos reais

**Files:**
- Modify: `index.html:316-339` (bloco `events.forEach`)

- [ ] **Step 1: Substituir o bloco de ingestão**

Localizar:

```js
    events.forEach(function(ev) {
      if (!ev.start || !ev.start.dateTime) return;
      var st = new Date(ev.start.dateTime);
      var en = new Date(ev.end.dateTime);
      var sH = st.getHours(), eH = en.getHours();
      var key = dk(st.getFullYear(), st.getMonth()+1, st.getDate());
      var ymK = st.getFullYear() + '-' + pad2(st.getMonth()+1);
      realMonths[ymK] = true;
      totalReal++;
      var label = 'HVC';
      if (sH >= 19 || sH < 7) label = 'HVC Noturno';
      else if (sH >= 7 && eH <= 13) label = 'HVC Diurno';
      else if (sH >= 13 && eH <= 19) label = 'HVC Tarde';
      else label = 'HVC Tarde+Noturno';
      var hrs = pad2(sH) + 'h-' + pad2(eH) + 'h';
      if (HVC[key]) {
        HVC[key].label = 'HVC (múltiplos)';
        HVC[key].eventCount = (HVC[key].eventCount || 1) + 1;
        var eS = parseInt(HVC[key].hours.split('h-')[0]);
        HVC[key].hours = pad2(Math.min(eS, sH)) + 'h-' + pad2(eH) + 'h';
      } else {
        HVC[key] = { label: label, hours: hrs, source: 'real', eventCount: 1 };
      }
    });
```

E substituir por:

```js
    events.forEach(function(ev) {
      if (!ev.start || !ev.start.dateTime) return;
      var st = new Date(ev.start.dateTime);
      var en = new Date(ev.end.dateTime);
      var sH = st.getHours(), eH = en.getHours();
      var w = (en.getTime() - st.getTime()) / (1000 * 60 * 60 * 12);
      var key = dk(st.getFullYear(), st.getMonth()+1, st.getDate());
      var ymK = st.getFullYear() + '-' + pad2(st.getMonth()+1);
      realMonths[ymK] = true;
      totalReal++;
      var label = 'HVC';
      if (sH >= 19 || sH < 7) label = 'HVC Noturno';
      else if (sH >= 7 && eH <= 13) label = 'HVC Diurno';
      else if (sH >= 13 && eH <= 19) label = 'HVC Tarde';
      else label = 'HVC Tarde+Noturno';
      var hrs = pad2(sH) + 'h-' + pad2(eH) + 'h';
      if (HVC[key]) {
        HVC[key].label = 'HVC (múltiplos)';
        HVC[key].eventCount = (HVC[key].eventCount || 1) + 1;
        HVC[key].weight = (HVC[key].weight || 0) + w;
        var eS = parseInt(HVC[key].hours.split('h-')[0]);
        HVC[key].hours = pad2(Math.min(eS, sH)) + 'h-' + pad2(eH) + 'h';
      } else {
        HVC[key] = { label: label, hours: hrs, source: 'real', eventCount: 1, weight: w };
      }
    });
```

Mudanças: adicionada linha `var w = ...` calculando duração em frações de 12h; campo `weight` populado tanto na criação inicial quanto no merge.

- [ ] **Step 2: Commit**

```bash
git add index.html
git commit -m "feat: compute weight per real HVC event (duration / 12h)"
```

---

## Task 3: Atribuir `weight` aos slots de projeção

**Files:**
- Modify: `index.html:343-359` (bloco `monthList.forEach` de projeções)

- [ ] **Step 1: Substituir os slots**

Localizar:

```js
  monthList.forEach(function(ym) {
    var ymK = ym[0] + '-' + pad2(ym[1]);
    if (realMonths[ymK]) return;
    var dim = new Date(ym[0], ym[1], 0).getDate();
    var wc = {};
    for (var i = 1; i <= dim; i++) { var dw = new Date(ym[0], ym[1]-1, i).getDay(); if(!wc[dw]) wc[dw]=[]; wc[dw].push(i); }
    var slots = [];
    if (wc[5]&&wc[5][0]) slots.push({d:wc[5][0],l:'HVC Noturno',h:'19h-07h'});
    if (wc[6]&&wc[6][1]) slots.push({d:wc[6][1],l:'HVC Diurno',h:'07h-19h'});
    if (wc[0]&&wc[0][1]) slots.push({d:wc[0][1],l:'HVC Tarde+Noturno',h:'13h-07h'});
    if (wc[2]&&wc[2][1]) slots.push({d:wc[2][1],l:'HVC Noturno',h:'19h-07h'});
    if (wc[5]&&wc[5][2]) slots.push({d:wc[5][2],l:'HVC Noturno',h:'19h-07h'});
    if (wc[2]&&wc[2][3]) slots.push({d:wc[2][3],l:'HVC Noturno',h:'19h-07h'});
    slots.forEach(function(s) {
      var key = dk(ym[0], ym[1], s.d);
      HVC[key] = { label: s.l, hours: s.h, source: 'projeção', eventCount: 1 };
    });
```

E substituir por:

```js
  monthList.forEach(function(ym) {
    var ymK = ym[0] + '-' + pad2(ym[1]);
    if (realMonths[ymK]) return;
    var dim = new Date(ym[0], ym[1], 0).getDate();
    var wc = {};
    for (var i = 1; i <= dim; i++) { var dw = new Date(ym[0], ym[1]-1, i).getDay(); if(!wc[dw]) wc[dw]=[]; wc[dw].push(i); }
    var slots = [];
    if (wc[5]&&wc[5][0]) slots.push({d:wc[5][0],l:'HVC Noturno',h:'19h-07h',w:1.0});
    if (wc[6]&&wc[6][1]) slots.push({d:wc[6][1],l:'HVC Diurno',h:'07h-19h',w:1.0});
    if (wc[0]&&wc[0][1]) slots.push({d:wc[0][1],l:'HVC Tarde+Noturno',h:'13h-07h',w:1.5});
    if (wc[2]&&wc[2][1]) slots.push({d:wc[2][1],l:'HVC Noturno',h:'19h-07h',w:1.0});
    if (wc[5]&&wc[5][2]) slots.push({d:wc[5][2],l:'HVC Noturno',h:'19h-07h',w:1.0});
    if (wc[2]&&wc[2][3]) slots.push({d:wc[2][3],l:'HVC Noturno',h:'19h-07h',w:1.0});
    slots.forEach(function(s) {
      var key = dk(ym[0], ym[1], s.d);
      HVC[key] = { label: s.l, hours: s.h, source: 'projeção', eventCount: 1, weight: s.w };
    });
```

Mudanças: cada slot ganha campo `w` (peso); a criação de `HVC[key]` passa a usar `weight: s.w`.

- [ ] **Step 2: Commit**

```bash
git add index.html
git commit -m "feat: assign explicit weight to HVC projection slots"
```

---

## Task 4: Cabeçalho mensal usa peso somado

**Files:**
- Modify: `index.html:466-471` (dentro de `renderMonth`)

- [ ] **Step 1: Substituir contadores**

Localizar:

```js
  var sc=0, hc=0, ec=0;
  for (var i=1;i<=dim;i++) { var k=dk(y,m,i); if(SOBREAVISOS[k])sc++; if(HVC[k]){hc++;ec+=(HVC[k].eventCount||1);} }

  var h = '<div class="month-section"><div class="month-hdr">' + mN;
  h += isR ? ' <span class="mtag real">✓ '+ec+' plt</span>' : ' <span class="mtag">⏳ '+hc+' plt</span>';
  h += ' <span class="mtag">'+sc+' sob</span></div><div class="cgrid">';
```

E substituir por:

```js
  var sc=0, wt=0;
  for (var i=1;i<=dim;i++) { var k=dk(y,m,i); if(SOBREAVISOS[k])sc++; if(HVC[k])wt+=(HVC[k].weight||0); }

  var h = '<div class="month-section"><div class="month-hdr">' + mN;
  h += isR ? ' <span class="mtag real">✓ '+fmtPlt(wt)+' plt</span>' : ' <span class="mtag">⏳ '+fmtPlt(wt)+' plt</span>';
  h += ' <span class="mtag">'+sc+' sob</span></div><div class="cgrid">';
```

Mudanças: `hc`/`ec` removidos; `wt` é a soma de `HVC[k].weight`. Tanto branch real quanto projeção passam a exibir `fmtPlt(wt)`.

- [ ] **Step 2: Commit**

```bash
git add index.html
git commit -m "feat: month header shows weighted plantão count"
```

---

## Task 5: Card de produção usa peso e R$ 1.700

**Files:**
- Modify: `index.html:442-452`

- [ ] **Step 1: Substituir bloco do card**

Localizar:

```js
  // Income
  h += '<div class="income"><h3>💰 Produção HVC</h3><p style="font-size:11px;color:#9CA3AF;margin-bottom:8px">R$ 1.600/plantão</p><div class="igrid">';
  var gt = 0;
  monthList.forEach(function(ym) {
    var cnt = 0, ymK = ym[0]+'-'+pad2(ym[1]), isR = !!realMonths[ymK];
    var dim = new Date(ym[0],ym[1],0).getDate();
    for (var d=1;d<=dim;d++) { var k=dk(ym[0],ym[1],d); if(HVC[k]) cnt+=(HVC[k].eventCount||1); }
    var amt = cnt*1600; gt += amt;
    h += '<div class="icard"><div class="mn">' + MONTHS_PT[ym[1]].substring(0,3) + '/' + String(ym[0]).substring(2) + (isR?' ✓':' ⏳') + '</div>';
    h += '<div class="amt">R$ ' + amt.toLocaleString('pt-BR') + '</div><div class="sc">' + cnt + ' plt</div></div>';
  });
  h += '</div><div class="itotal">Total: R$ ' + gt.toLocaleString('pt-BR') + '</div></div>';
```

E substituir por:

```js
  // Income
  h += '<div class="income"><h3>💰 Produção HVC</h3><p style="font-size:11px;color:#9CA3AF;margin-bottom:8px">R$ 1.700/plantão</p><div class="igrid">';
  var gt = 0;
  monthList.forEach(function(ym) {
    var wt = 0, ymK = ym[0]+'-'+pad2(ym[1]), isR = !!realMonths[ymK];
    var dim = new Date(ym[0],ym[1],0).getDate();
    for (var d=1;d<=dim;d++) { var k=dk(ym[0],ym[1],d); if(HVC[k]) wt+=(HVC[k].weight||0); }
    var amt = wt*1700; gt += amt;
    h += '<div class="icard"><div class="mn">' + MONTHS_PT[ym[1]].substring(0,3) + '/' + String(ym[0]).substring(2) + (isR?' ✓':' ⏳') + '</div>';
    h += '<div class="amt">R$ ' + amt.toLocaleString('pt-BR') + '</div><div class="sc">' + fmtPlt(wt) + ' plt</div></div>';
  });
  h += '</div><div class="itotal">Total: R$ ' + gt.toLocaleString('pt-BR') + '</div></div>';
```

Mudanças: label da taxa `R$ 1.600` → `R$ 1.700`; `cnt` (eventCount) → `wt` (weight); multiplicador `1600` → `1700`; exibição `cnt + ' plt'` → `fmtPlt(wt) + ' plt'`.

- [ ] **Step 2: Commit**

```bash
git add index.html
git commit -m "feat: production card uses weighted count at R$ 1.700/plantão"
```

---

## Task 6: Detalhe do dia mostra peso ponderado

**Files:**
- Modify: `index.html:538-542` (dentro de `showSheet`)

- [ ] **Step 1: Substituir bloco hvc**

Localizar:

```js
  if(hvc){
    var st=hvc.source==='real'?'✓ Pega Plantão':'⏳ Projeção';
    h+='<div class="ditem"><div class="dicon" style="background:'+(hvc.source==='real'?'#0891B2':'#155E75')+'"></div>'+hvc.label+' ('+hvc.hours+')<br><span style="color:#9CA3AF;font-size:11px">'+st+'</span></div>';
    if(hvc.eventCount>1) h+='<div class="ditem" style="color:#9CA3AF;padding-left:16px">'+hvc.eventCount+' turnos neste dia</div>';
  }
```

E substituir por:

```js
  if(hvc){
    var st=hvc.source==='real'?'✓ Pega Plantão':'⏳ Projeção';
    h+='<div class="ditem"><div class="dicon" style="background:'+(hvc.source==='real'?'#0891B2':'#155E75')+'"></div>'+hvc.label+' ('+hvc.hours+')<br><span style="color:#9CA3AF;font-size:11px">'+st+' · '+fmtPlt(hvc.weight||0)+' plt</span></div>';
    if(hvc.eventCount>1) h+='<div class="ditem" style="color:#9CA3AF;padding-left:16px">'+hvc.eventCount+' turnos neste dia</div>';
  }
```

Mudança: adicionado ` · ${fmtPlt(weight)} plt` ao texto cinza embaixo do label, mostrando o peso ponderado de qualquer dia (com 1 ou múltiplos turnos).

- [ ] **Step 2: Commit**

```bash
git add index.html
git commit -m "feat: day detail shows weighted plantão count"
```

---

## Task 7: Push e verificação em produção

**Files:** nenhum (verificação)

- [ ] **Step 1: Push para `main`**

```bash
git push origin main
```

GitHub Pages republica em ~30-60s.

- [ ] **Step 2: Aguardar deploy e abrir página**

Em Playwright:

```js
await browser_navigate('https://arthurkingayres-ux.github.io/agenda-consolidada/')
await browser_snapshot()
```

Confirmar que carregou sem precisar relogar (token cacheado).

- [ ] **Step 3: Verificar Maio/2026 — caso de referência**

Inspecionar o snapshot ou rodar:

```js
await browser_evaluate(`() => {
  const mai = Object.keys(HVC).filter(k => k.startsWith('2026-05'))
    .reduce((acc, k) => acc + (HVC[k].weight || 0), 0);
  return { mai_weight: mai, mai_amt: mai * 1700 };
}`)
```

Expected: `{ mai_weight: 5.5, mai_amt: 9350 }`

E no DOM, o cabeçalho de "Maio 2026" deve mostrar `✓ 5,5 plt` e o card de produção deve mostrar `R$ 9.350` / `5,5 plt`.

- [ ] **Step 4: Verificar Abril/2026 — outro mês real**

Rodar:

```js
await browser_evaluate(`() => {
  const abr = Object.keys(HVC).filter(k => k.startsWith('2026-04'))
    .reduce((acc, k) => acc + (HVC[k].weight || 0), 0);
  return { abr_weight: abr, abr_amt: abr * 1700 };
}`)
```

Conferir que o `abr_weight` retornado bate com o que aparece no cabeçalho de Abril (atualmente exibe `10 plt` antes da mudança — depois deve mostrar peso ponderado real, que pode ser fracionário).

- [ ] **Step 5: Verificar mês de projeção**

Conferir cabeçalho de Setembro/2026 (ou primeiro mês ⏳). Antes mostrava `6 plt`. Depois deve mostrar `6,5 plt` quando o mês incluir o slot de tarde+noturno (peso 1,5), ou continuar `6 plt` se não incluir.

Rodar:

```js
await browser_evaluate(`() => {
  const set = Object.keys(HVC).filter(k => k.startsWith('2026-09'))
    .map(k => ({ date: k, weight: HVC[k].weight, source: HVC[k].source }));
  return set;
}`)
```

Cada entrada deve ter `source: 'projeção'` e `weight` em {1.0, 1.5}.

- [ ] **Step 6: Verificar total**

Conferir que "Total: R$ X" no rodapé do card de produção bate com a soma manual dos `amt` dos 12 meses.

- [ ] **Step 7: Verificar dia com múltiplos turnos**

No DOM, clicar em 9/mai (ou 10/mai). O detalhe do dia deve mostrar `1 plt` para 9/mai (0,5 + 0,5) e `1,5 plt` para 10/mai (0,5 + 1,0), além da linha "2 turnos neste dia".

- [ ] **Step 8: Verificar dia com plantão único de 6h**

Não há plantão único de 6h em maio nos dados atuais (todos os 6h estão emparelhados). Pular este passo se não houver caso real; do contrário, abrir o detalhe e confirmar `0,5 plt`.

- [ ] **Step 9: Sem novo commit**

Esta task é só verificação. Se algo divergir, voltar à task correspondente, corrigir, commitar e re-push.
