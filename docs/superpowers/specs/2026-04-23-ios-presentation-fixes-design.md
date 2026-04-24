# Fix: Apresentação do PWA Agenda Consolidada no iOS

**Data:** 2026-04-23
**Projeto:** [arthurkingayres-ux/agenda-consolidada](https://github.com/arthurkingayres-ux/agenda-consolidada)
**Live:** https://arthurkingayres-ux.github.io/agenda-consolidada/

## Contexto

O PWA está em produção e o artefato agradou ao usuário. Dois bugs bloqueiam o uso no iOS:

1. **Textos, acentos e emojis aparecem corrompidos** (ex.: "MarÃ§o" em vez de "Março", símbolos "â " em vez de "⚠").
2. **Ao clicar em "Entrar com Google", aparece aviso de app não verificado**, exigindo confirmações de segurança a cada login.

Diagnóstico realizado via Playwright com viewport iOS (393×852) e leitura do source no repo remoto.

### Causa raiz

**Bug 1:** O `index.html` no repo foi commitado com **mojibake** (UTF-8 duplamente codificado) salvo literalmente no arquivo. O `<meta charset>` está correto e o GitHub Pages envia `Content-Type: text/html; charset=utf-8`, mas os bytes do arquivo já estão corrompidos. A tela de login renderiza OK porque usa HTML entities (`&otilde;`), mas todo o dashboard (render, sheet, banner) usa strings JS contaminadas.

**Bug 2:** O OAuth consent screen está em "In production" com scope sensível (`calendar.readonly`) sem verificação do Google → warning obrigatório "Google hasn't verified this app" para todos usuários.

### Achados adicionais (incluídos no escopo)

- Erro 404 em `/favicon.ico` no console
- Warning: `apple-mobile-web-app-capable` está deprecated — falta a versão moderna `mobile-web-app-capable`
- `apple-touch-icon` aponta para SVG — suporte limitado em iOS antigo, pode mostrar ícone genérico quando instalado na home screen

## Escopo

### O que está incluído

- Corrigir todas as ocorrências de mojibake no `index.html`
- Gerar ícones PNG (192 e 512) e referenciá-los no `manifest.json` + `<head>`
- Adicionar `<link rel="icon">` (elimina 404)
- Adicionar `<meta name="mobile-web-app-capable">`
- Documentar passo-a-passo para o usuário mudar OAuth para Testing mode
- Deploy via commit + push para `main`
- Verificação final via Playwright em viewport iOS

### O que está fora

- Submeter app OAuth para verificação formal do Google (trade-off aceito: relogin semanal em Testing mode)
- Mudar a stack de auth (ICS proxy, service account, etc.)
- Outras features da lista "possíveis próximos passos" (notificações push, dark mode, .ics export, etc.)
- Refactor estrutural do `index.html` (permanece single-file)

## Design

### Componente 1: Correção de mojibake em `index.html`

**Método:** Substituições pontuais via `Edit` tool (`old_string` → `new_string`), mantendo contexto suficiente para garantir unicidade. Arquivo salvo em UTF-8 sem BOM.

**Mapeamento de correções** (~25 trechos):

| Local | De (mojibake) | Para (UTF-8 correto) |
|---|---|---|
| `<title>` L12 | `Agenda Consolidada â Arthur` | `Agenda Consolidada — Arthur` |
| Comentário CONFIG L138 | `CONFIG â Substitua` | `CONFIG — Substitua` |
| `MONTHS_PT` L145 | `'MarÃ§o'` | `'Março'` |
| `WD_NAMES` L147 | `'TerÃ§a'`, `'SÃ¡bado'` | `'Terça'`, `'Sábado'` |
| `FERIADOS` L191-202 | `PaixÃ£o`, `IndependÃªncia`, `ProclamaÃ§Ã£o`, `ConsciÃªncia`, `ConceiÃ§Ã£o`, `VÃ©spera`, `SuspensÃ£o`, `ConfraternizaÃ§Ã£o` | `Paixão`, `Independência`, `Proclamação`, `Consciência`, `Conceição`, `Véspera`, `Suspensão`, `Confraternização` |
| `loadData` L261 | `Pega PlantÃ£o` | `Pega Plantão` |
| `loadData` L281 | `HVC (mÃºltiplos)` | `HVC (múltiplos)` |
| Projection L307 | `'projeÃ§Ã£o'` | `'projeção'` |
| Render note L350 | `Pega PlantÃ£o`, `Â·`, `projeÃ§Ã£o` | `Pega Plantão`, `·`, `projeção` |
| Income title L391 | `ProduÃ§Ã£o` | `Produção` |
| Sheet L488 | `Pega PlantÃ£o`, `ProjeÃ§Ã£o` | `Pega Plantão`, `Projeção` |
| Month label L412 | `FÃRIAS` | `FÉRIAS` |
| Banner badges L343-347 | `â ` (warning) | `⚠` |
| HVC badges L345, L355-356, L398, L419 | `â` (check), `â³` (hourglass) | `✓`, `⏳` |
| Conflict list L383, L385 | `â ` | `⚠` |
| Conflicts inline L385, L492 | `Ã` (times) | `×` |
| Income title L391 | `ð°` | `💰` |
| Sheet hol L481 | `ð` | `📅` |
| Calendar cell icons L445-446 | `ð`, `ðµ`, `â³`, `ð¢` | `📅`, `🔵`, `⏳`, `🟢` |
| Accordion L374, L466 | `ð`, `ð` | `📅`, `📁` |
| Refresh hint L403 | `â»` | `♻` |

**Verificação:** após edits, `grep -nP '[ÃâðÂ]' index.html` deve retornar zero matches (fora de URLs/paths legítimos).

### Componente 2: Ícones PNG para iOS

**Geração:** criar `icon-192.png` e `icon-512.png` a partir do design existente (quadrado azul `#1E3A5F` com letra "A" branca centralizada).

- Preferência: Python + Pillow (se disponível no sistema)
- Fallback: script Node com `sharp`, ou conversão manual via ferramenta online se ambiente não permitir
- Design deve bater pixel-perfect com os SVGs existentes (mesmo azul, letra centralizada, sem padding estranho)

**Atualizações em arquivos:**

**`index.html` `<head>`:**
```html
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">  <!-- manter para iOS legado -->
```

**`manifest.json`:** `icons` array com PNG 192 + PNG 512 como principais, SVG 192 + SVG 512 como secundários.

### Componente 3: Mudança de OAuth para Testing (instruções ao usuário)

Não é código — é configuração no Google Cloud Console. Documento de passos claros no spec, para o usuário executar sozinho:

1. Acessar [console.cloud.google.com](https://console.cloud.google.com) → projeto `skilful-firefly-494220-m4`
2. APIs & Services → OAuth consent screen
3. Publishing status → clicar **"Back to testing"**
4. Em "Test users", clicar "+ Add users", adicionar `arthurkingayres@gmail.com`, salvar
5. Trade-off aceito: token expira a cada 7 dias → relogin semanal

**Impacto esperado:** warning muda de "Google hasn't verified this app - Advanced - Go to (unsafe)" para "App is being tested - Continue" (UX muito mais amigável para single-user).

### Componente 4: Deploy e verificação

**Deploy:**
1. `git clone https://github.com/arthurkingayres-ux/agenda-consolidada.git` na pasta atual (mesclando com `prompt-retomada.md` existente)
2. Aplicar edits do Componente 1 em `index.html`
3. Gerar PNGs (Componente 2) e salvar na raiz do repo
4. Atualizar `manifest.json` e `<head>`
5. Commit único: "Fix iOS presentation: mojibake, PWA icons, meta tags"
6. `git push origin main` → GitHub Pages rebuild (~1min)

**Verificação pós-deploy:**
1. Playwright: `browser_navigate` com viewport 393×852
2. `browser_snapshot` → confirmar `Page Title: Agenda Consolidada — Arthur` (não mais `â`)
3. `browser_console_messages` → zero 404s, zero deprecation warnings
4. `browser_evaluate`: `fetch('/agenda-consolidada/index.html').then(r=>r.text()).then(t=>/[Ã¡Ã§Ã£Ã©ÃªÃºâð]/.test(t))` deve retornar `false` para mojibake (observando false positives em `Ã` de "à" correto)
5. Usuário confirma no iPhone real: warning OAuth mais amigável + emojis/acentos corretos no dashboard

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `index.html` | ~25 edits cirúrgicos (Componente 1 + 2 head) |
| `manifest.json` | icons array atualizado |
| `icon-192.png` | **NOVO** |
| `icon-512.png` | **NOVO** |

Total: 2 arquivos modificados, 2 arquivos novos. Zero mudanças em `sw.js` e SVGs.

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Geração de PNG indisponível no ambiente (Python/Pillow ausente) | Fallback documentado: usuário gera via ferramenta online ou deixa SVG apenas (iOS 12+ aceita) |
| Edit falha por `old_string` não único | Incluir 2-3 linhas de contexto em cada edit; fallback para `replace_all` quando mojibake é idêntico em múltiplas linhas |
| Push rejeitado (sem credenciais git locais) | Se push automatizado falhar, usuário sobe os diffs via GitHub web UI ou configura credenciais |
| Conversão de mojibake em chars errados (ex.: `Ã` em URL legítima) | Grep pós-fix só busca mojibake *sequencial* (`Ã§`, `Ã£`, `Ã©`, `â[ ³»]`); revisar diff manualmente antes do commit |

## Critérios de sucesso

- [ ] Page title na aba do browser aparece `Agenda Consolidada — Arthur` (em-dash, não `â`)
- [ ] Dashboard no iOS exibe `Março`, `Terça`, `Sábado`, `Pega Plantão`, `projeção` com acentos corretos
- [ ] Banner mostra `⚠ CONFLITO` (não `â `), `✓` em HVC real, `⏳` em projeção
- [ ] Emoji `💰` no título de Produção HVC; `📅`, `🔵`, `🟢`, `♻` aparecem normalmente
- [ ] Console no DevTools iOS: zero 404 para `favicon.ico`, zero deprecation warning
- [ ] Ícone PWA correto na home screen do iPhone quando instalado
- [ ] OAuth warning mostra "App is being tested" (não "hasn't been verified") após o usuário mudar para Testing mode

## Fora do escopo (follow-ups possíveis)

- Escolher e implementar uma das 7 ideias de feature do prompt-retomada (notificações push, dark mode, .ics export, sincronização bidirecional, config de usuário, automação de obtenção de dados UNICAMP/HVC)
- Automatizar atualização dos sobreavisos quando sair nova escala UNICAMP
- Splash screen iOS (`apple-touch-startup-image`)
- Testes automatizados (não há suite atualmente)
