# BR no GTA: plano completo (versão revisada)
*Revisão de 11/10/2026 (horário de Brasília). Substitui o `br_no_gta_estrategia_viral.md` onde houver conflito. Contexto geral em `/workspace/plano_renda.md`.*
*Os números citados vêm de páginas oficiais, com link. Onde algo não foi confirmado, está marcado "não verificado". Regras das plataformas mudam: confira o link antes de agir.*

---

## 0. Diretrizes do dono (valem acima de tudo)
1. **Produção é minha, publicação é do Luiz.** Eu entrego **pacotes prontos para publicar**. O Luiz publica manualmente, quando quiser e no horário que quiser. **Não existe grade de horários neste plano.** Cada pacote informa só *a partir de quando* pode sair e *até quando* faz sentido (validade).
2. **Canal de referência em conteúdo OFICIAL de GTA VI.** Sem rumor, especulação, vazamento, "teoria" ou "boato x verdade". Se a Rockstar não informou, a resposta do vídeo é "a Rockstar ainda não informou".
3. Custo zero e ferramentas open source. Revisão humana antes de qualquer publicação. Trilha só do Hazewave. IA declarada. #publi em todo conteúdo com link de afiliado.

---

## 1. Posicionamento: "a referência em GTA VI oficial, em português"
**Promessa do canal:** "Tudo o que a Rockstar confirmou sobre GTA VI, explicado em português, com fonte."

**Fontes aceitas** (todo fato precisa de uma delas, com data):
- Rockstar: rockstargames.com/VI, Newswire, canais oficiais da Rockstar no YouTube e no X, e o suporte oficial.
- Take-Two: comunicados e relatórios para investidores (take2games.com/ir e o press release das pré-vendas: https://taketwointeractivesoftwareinc.gcs-web.com/news-releases/news-release-details/rockstar-games-announces-pre-orders-grand-theft-auto-vi).
- Lojas oficiais: PlayStation Store BR e Microsoft Store/Xbox BR (preço, edições, idiomas, pré-carga).
- Parceiros oficiais da Rockstar, como a Netflix/Tudum no Extended Look: https://www.netflix.com/tudum/articles/grand-theft-auto-6-extended-first-look
- Imprensa **só para citar algo oficial** (uma entrevista, um número da Take-Two). Nunca como fonte de rumor.

**Fica fora do canal:**
- vazamentos (incluindo "Cyberleek"), "insiders", datamining, teorias, "vai ser adiado?", "gone gold?" antes de anúncio oficial
- mods, cheats, glitches, "dinheiro infinito", "GTA 6 APK", versões para PS4 ou celular
- trailers dublados por IA ou reenviados

**Formatos que resolvem perguntas de "sim ou não" usando só o oficial:**
- "GTA 6 vai sair pra PS4? A resposta oficial": as plataformas anunciadas são PS5 e Xbox Series X|S.
- "GTA 6 vai ser dublado? O que a loja oficial diz": confira os idiomas na página da PS Store BR no dia da gravação (https://store.playstation.com/pt-br/product/EP1004-PPSA01547_00-GTAVISTANDARD001).

---

## 2. Fluxo: produção → pacote pronto → publicação manual (Luiz)

### 2.1 Estados do pacote
`pauta` → `roteiro aprovado` → `render` → `QA (checklist §3.9)` → **`PRONTO`** → (Luiz publica) → `PUBLICADO` (o Luiz anota data e link)

### 2.2 O que vem em cada pacote (pasta `content/videos/<AAAA-MM-DD>-<slug>/`)
```text
PUBLICAR.md            passo a passo para o Luiz (abaixo), com validade e gatilho
video/master_16x9.mp4  vídeo longo final (sem marca d'água de nenhum app)
video/legendas_ptbr.srt legenda para enviar no YouTube
thumbs/A.png B.png C.png  1280x720 (A = padrão; B e C para o teste A/B do YouTube)
metadados.md           3 títulos (A/B/C), descrição completa com capítulos, hashtags, playlist, cartões e tela final
declaracoes.md         valores exatos: Uso de IA (Sim/Não e por quê), Promoção paga (Sim/Não), Público-alvo (não é para crianças), restrição de idade, idioma
fontes.md              todas as fontes oficiais com URL e data de checagem
cortes/<n>-<angulo>/   versões 9:16 por plataforma (§6), com legenda pronta de cada rede
aprovacao.md           checklist §3.9 assinado (nome e data)
```

### 2.3 Modelo de `PUBLICAR.md`
```text
PACOTE: GTA 6 no Brasil: preço, idiomas e pré-carga (tudo oficial)
PODE PUBLICAR A PARTIR DE: agora    |   VALIDADE: até 18/11/2026 (depois disso, atualizar o preço e os idiomas)
GATILHO (se houver): —
YOUTUBE (vídeo longo):
  1. Studio > Criar > Enviar > video/master_16x9.mp4
  2. Título: (A) de metadados.md  |  Thumbnail: thumbs/A.png
  3. Descrição: copiar de metadados.md (já tem #publi na 1ª linha, se houver link)
  4. Mostrar mais > Promoção paga: [SIM/NÃO]  |  Uso de IA (conteúdo alterado ou sintético): [SIM/NÃO]
  5. Legendas: enviar video/legendas_ptbr.srt
  6. Playlist: "Guia Oficial GTA VI"  |  Tela final: vídeo X  |  Cartão em 03:10: vídeo Y
  7. Depois de publicar: Testar e comparar > enviar thumbs B e C (se o canal tiver acesso)
SHORTS / TIKTOK / REELS / FACEBOOK: ver cortes/*/LEIA.md (pode publicar em qualquer dia e horário; não há ordem obrigatória)
DEPOIS: anotar data e link em aprovacao.md
```

**Validade:** pacotes **perenes** (guias) não têm validade, só "revisar em [data]". Pacotes de **anúncio oficial** valem por poucos dias e trazem `GATILHO: só publicar se...`. Opcional: o workflow que já existe no repositório (`.github/workflows/youtube-private-upload-worker.yml`) pode enviar o vídeo como **privado**, e o Luiz só troca para público quando quiser. O upload manual também vale.

---

## 3. Monetização: regras oficiais e o que cada uma muda na produção

### 3.1 Requisitos do YPP (Brasil)
| Nível | Requisitos | Fonte |
|---|---|---|
| YPP expandido (Super Thanks, membros, Shopping próprio) | 500 inscritos + 3 vídeos públicos nos últimos 90 dias + **3.000 h** de exibição pública de vídeos longos em 12 meses **ou** **3 milhões** de views válidas de Shorts em 90 dias | https://support.google.com/youtube/answer/13429240?hl=pt-BR |
| Receita de anúncios | 1.000 inscritos + **4.000 h** em 12 meses **ou** **10 milhões** de views válidas de Shorts em 90 dias. Também é preciso seguir as políticas, não ter aviso ativo das Diretrizes da Comunidade, ter verificação em duas etapas e uma conta AdSense vinculada | https://support.google.com/youtube/answer/72851?hl=pt-BR |
| Programa de Afiliados do YouTube Shopping (BR) | Estar no YPP com **mais de 5.000 inscritos**, morar no Brasil e não ser canal de música nem infantil. Lojas: Shopee e Mercado Livre | https://blog.youtube/intl/pt-br/news-and-events/yt-shopping-afiliados-brasil/ · https://support.google.com/youtube/answer/13376398?hl=pt-BR |

**Na produção:**
- O "3 vídeos em 90 dias" já se cumpre com o plano.
- Para chegar às horas de exibição, o eixo é **vídeo longo perene e buscável** (§4).
- Shorts servem de descoberta. A meta de views de Shorts conta só **views válidas**, não as views do contador público (https://support.google.com/youtube/answer/10059070).
- **O YouTube revisa o canal inteiro** na candidatura: tema principal, vídeos mais vistos, mais recentes, com mais tempo de exibição e metadados (https://support.google.com/youtube/answer/1311392?hl=pt-BR). **Antes de pedir o YPP, revise os 10 vídeos mais vistos do canal** com o checklist §3.9.

### 3.2 Conteúdo "inautêntico" (produzido em massa ou repetitivo)
**O que diz a política:** desde 15/07/2025, conteúdo "produzido em massa, genérico, repetitivo ou manipulador" não monetiza. O conteúdo precisa "divertir ou educar, e não apenas gerar visualizações". Na versão em português a política se chama "conteúdo não original"; em inglês, "inauthentic content".
https://support.google.com/youtube/answer/1311392?hl=pt-BR · contexto: https://techcrunch.com/2026/07/20/youtube-clarifies-policies-around-ai-slop-and-upsetting-videos/

**Regras de produção:**
- Cada vídeo responde uma **pergunta diferente**, com **roteiro escrito para ele**. Proibido trocar só o tema num roteiro-modelo.
- Mudar estrutura e abertura entre episódios da mesma série: mesma identidade visual, mas argumento, ordem e exemplos próprios.
- Narração com voz sintética: variar ritmo e entonação, ter **opinião e análise** e, sempre que possível, **voz real** do apresentador em parte do vídeo.
- Proibido gerar vídeos em lote a partir de uma lista de tópicos sem revisão editorial. O pipeline sempre passa pela skill `gta6-editorial` mais revisão humana.
- Registrar em `brain/memory/` os ganchos e estruturas dos últimos 10 vídeos. O QA bloqueia repetição.

### 3.3 Conteúdo reutilizado (material de terceiros, incluindo trailers da Rockstar)
**O que diz a política:** reutilizar conteúdo "sem adicionar comentários originais significativos, modificações substanciais ou valor educacional ou de entretenimento" não monetiza, e a avaliação vale **para o canal inteiro**.
- Exemplos aceitos: "clipes para análise crítica", "reações em que você comenta o vídeo original".
- Exemplos não aceitos: "clipes editados juntos com pouca ou nenhuma narrativa", "reações principalmente não verbais".
https://support.google.com/youtube/answer/1311392?hl=pt-BR · vídeo oficial explicando: https://www.youtube.com/watch?v=YPrCfgbX71E

**Regras de produção:**
- **Nunca reenviar trailer ou Extended Look** inteiro, "legendado" ou "dublado".
- Trecho oficial só **dentro de análise**: a narração explica *o que aquilo mostra* enquanto o trecho roda. Nada de trecho longo "solto" sem fala.
- Em todo vídeo, uma camada **própria** por cima: gráficos, mapas desenhados, comparativos, tabelas, texto de análise.
- Em Shorts, a regra é a mesma: cada corte tem narração e argumento próprios.

### 3.4 Direitos autorais e Content ID
**O que diz a política:**
- Uma **reivindicação do Content ID** não é **aviso de direitos autorais (strike)**. A reivindicação pode bloquear, monetizar para o dono ou só rastrear o vídeo.
- **Shorts de 1 a 3 minutos com reivindicação ativa são bloqueados**, qualquer que seja a política escolhida pelo dono.
- Disputa sem motivo válido pode virar pedido de remoção, e aí vem o strike.
- Se a disputa for aberta em até 5 dias, a receita fica retida desde o dia da reivindicação.

https://support.google.com/youtube/answer/6013276 · https://support.google.com/youtube/answer/7002106 · https://support.google.com/youtube/answer/7000961 · https://support.google.com/youtube/answer/2797454

**Regras de produção:**
- **Áudio:** só narração própria e **Hazewave**. Remover música licenciada do jogo e dos trailers (rádio, trilha do trailer). Se o trecho tiver música, abaixe ou substitua por Hazewave, ou use o trecho sem som.
- **Hazewave:** se as faixas forem cadastradas no Content ID por uma distribuidora, **liberar o canal BR no GTA** antes de usá-las (ou não cadastrar as faixas usadas como trilha). Senão o canal reivindica o próprio vídeo. Confira o processo na distribuidora escolhida (não verificado).
- **Shorts com mais de 60 s:** teste extra de áudio, porque uma reivindicação bloqueia o Short.
- **Reivindicação recebida:** primeiro **corte ou silencie o trecho** (Studio > Editor). Só dispute com motivo claro e documentado.

### 3.5 Diretrizes de conteúdo adequado para anunciantes (ícone amarelo)
**O que diz a política (jogos):**
- Violência gráfica de jogo **na thumbnail ou nos primeiros 7 segundos**: sem receita de anúncios.
- Violência gráfica de jogo **entre 8 e 15 segundos**: receita limitada.
- Violência gráfica **depois de 15 s**: em geral elegível.
- **Sem receita**, sempre: matança em massa de NPCs feita para chocar, violência sexual, tortura, violência contra crianças e violência contra pessoa real nomeada.
- **Palavrão forte** nos primeiros 7 s ou na maior parte do vídeo pode limitar a receita.

https://support.google.com/youtube/answer/10291745 · https://support.google.com/youtube/answer/6162278 · https://support.google.com/youtube/answer/9725604 · ícones: https://support.google.com/youtube/answer/9208564

**Regras de produção:**
- **Thumbnail e primeiros 15 s sem sangue, tiro em close, corpo ou ferimento.** Abra com o personagem, o mapa, o carro, o rosto do apresentador ou um gráfico.
- Ação policial e tiroteio do material oficial só depois dos 15 s e em ritmo de análise, nunca como "compilação de violência".
- Sem palavrão no gancho. No roteiro inteiro, linguagem leve.
- Preencher com honestidade a **autocertificação** (questionário de adequação ao anunciante) no envio. Se o ícone amarelo vier errado, **peça revisão humana** (https://support.google.com/youtube/answer/7083671).

### 3.6 Conteúdo alterado ou sintético (IA)
**O que diz a política:** é obrigatório informar no envio (Studio > "Uso de IA" / conteúdo alterado ou sintético) quando o conteúdo realista foi gerado ou alterado de forma significativa e pode ser confundido com pessoa, lugar ou evento reais. O YouTube também pode aplicar o rótulo automaticamente.
https://support.google.com/youtube/answer/14328491 · https://support.google.com/youtube/answer/15447836
**Nas outras plataformas:** o TikTok exige o rótulo em conteúdo realista gerado por IA (https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content).

**Regras de produção (preencher em `declaracoes.md`):**
- **Narração com voz clonada do apresentador** (há config de voz no repositório): marcar **Sim**, porque é a voz de uma pessoa real gerada sinteticamente.
- **Imagem realista gerada por IA** (cenário, pessoa): marcar **Sim**. O ideal é não usar.
- **Roteiro com ajuda de IA, legendas automáticas, correção de cor ou gráficos claramente ilustrativos:** em geral não exigem o aviso. Confira a lista de exemplos da página antes de cada caso novo.
- **Na dúvida, marque Sim.** Declarar não penaliza; omitir pode gerar rótulo automático e problema de política.

### 3.7 Política de conteúdo de fã da Rockstar
**O que diz a política:**
- A Rockstar permite que fãs publiquem material dos jogos para uso **não comercial** e pode pedir remoção a qualquer momento.
- Material **vazado** antes do lançamento é removido.
- Vídeos que mostram **finais, grandes revelações de história ou cutscenes isoladas** estão sujeitos a remoção.
- Cutscenes podem aparecer dentro de um gameplay mais amplo ou de um Let's Play narrado.

https://support.rockstargames.com/articles/7bNaeoMFTV0iUDGhStTXvz/policy-on-posting-copyrighted-rockstar-games-material

**Tensão a conhecer:** o YouTube pede que o criador tenha **direito de uso comercial** de tudo que monetiza. Para jogos sem licença comercial explícita, o uso do jogo deve ser **mínimo**, a não ser que o comentário tenha valor instrutivo ou educativo **ligado à ação mostrada** (https://support.google.com/youtube/answer/2490020). A Rockstar fala em "não comercial". Na prática, há canais de GTA monetizados há anos (ver `plano_renda.md`), mas **não existe garantia**.

**Regras de produção:**
- Comentário educativo **sempre ligado ao que está na tela**.
- Nada de gameplay longo sem narração.
- Nada de cutscene isolada.
- **Depois de 19/11:** zero spoiler de história em título, thumbnail, primeiros 60 s e cortes. Vídeos sobre história só com "⚠️ Spoiler" no título e cutscenes dentro de gameplay narrado.
- Manter um **plano B monetizável** sem material do jogo: explicações com gráficos próprios, mapas desenhados, tabelas de preço e o apresentador em câmera.

### 3.8 Monetização nas outras plataformas (referência)
| Plataforma | Requisitos | Fonte |
|---|---|---|
| TikTok: Programa de Recompensas do Criador (BR) | 18 anos ou mais, morar no Brasil, conta pessoal, **10.000 seguidores**, **100.000 views** nos últimos 30 dias. Vídeos com **pelo menos 1 minuto**, originais, sem dueto ou costura e não patrocinados | https://www.tiktok.com/legal/page/global/tiktok-creator-rewards-program-br/pt-BR |
| Facebook: monetização de conteúdo | Programa **por convite**. O Brasil está entre os países elegíveis. Conteúdo não original ou com edição mínima **não monetiza** e não é recomendado para quem não segue | https://www.facebook.com/business/help/267128784014981 · https://www.facebook.com/business/help/3382366608650437 |

### 3.9 Checklist de QA para monetização (vai assinado em `aprovacao.md`)
- [ ] **Só oficial:** todo fato com fonte oficial e data em `fontes.md`. Nenhum rumor, vazamento ou "teoria".
- [ ] **Roteiro original:** pergunta própria. Estrutura e gancho diferentes dos últimos 10 (`brain/memory`).
- [ ] **Transformação:** narração analítica sobre todo trecho oficial e camada própria (gráfico, mapa, texto). Nenhum trecho longo sem fala. Nenhum reenvio de trailer.
- [ ] **Áudio:** só narração + Hazewave. Música de trailer ou rádio removida ou silenciada.
- [ ] **Primeiros 15 s e thumbnail** sem violência gráfica. Sem palavrão no gancho.
- [ ] **Nada de** mod, cheat, glitch, cutscene isolada ou spoiler de história (depois de 19/11).
- [ ] **IA:** campo "Uso de IA" definido e justificado (voz clonada = Sim).
- [ ] **Publicidade:** link de afiliado = "Promoção paga" marcada + #publi na 1ª linha da descrição e da legenda + aviso falado.
- [ ] **Metadados honestos:** o título e a thumbnail cumprem o que prometem, sem "VAZOU", "LEAK" ou "MOD".
- [ ] **Cortes 9:16:** sem marca d'água de outro app, cada um com gancho próprio (§6).
- [ ] **Aprovado por:** ______ em __/__/____

---

## 4. Plano editorial de autoridade em busca

### 4.1 Séries (cada série vira uma playlist)
| Série / playlist | O que é | Exemplos de episódio (só oficial) |
|---|---|---|
| **Guia Oficial GTA VI** (perene) | Respostas diretas às perguntas mais buscadas | "Quando lança GTA 6? Data oficial e horário", "GTA 6 vai sair pra PS4? A resposta oficial", "GTA 6 em quais consoles?", "GTA 6 tem PC? O que a Rockstar disse", "GTA 6 é dublado? Idiomas oficiais" |
| **GTA VI no Brasil** | Preço em R$, edições, idiomas, pré-venda e pré-carga, classificação indicativa | "GTA 6: quanto custa no Brasil (Standard x Ultimate)", "Pré-carga de GTA 6: como fazer no PS5 e no Xbox" |
| **Raio-X Oficial** | Análise detalhada de trailers e do Extended Look | Vídeo A ("o que 27 minutos realmente revelaram"), "Trailer 1, 2 e 3: o que cada um confirmou", "A polícia de GTA 6 segundo o material oficial" |
| **Leonida Explicada** | Lugares e regiões mostrados oficialmente | "Vice City e Leonida: as regiões que a Rockstar mostrou", "Mapa oficial: o que já se sabe" (só o oficial, sem mapa de fã) |
| **Personagens Oficiais** | Jason, Lucia e elenco apresentado pela Rockstar | "Lucia e Jason: tudo que a Rockstar contou", "Raul Bautista: o que o Extended Look mostrou" |
| **GTA V x GTA VI** | Comparações só com material oficial dos dois jogos | "Polícia", "Atividades", "Interface e minimapa" |
| **Primeiras Horas** (depois de 19/11) | Guias práticos com gameplay próprio narrado, sem spoiler | "Como ganhar dinheiro no começo", "Todas as atividades do início", "Configurações recomendadas no PS5" |
| **Confirmado pela Rockstar** | Notícia oficial curta (validade baixa) | Publicado só com anúncio oficial: patch, data, edição, trailer novo |

### 4.2 Palavras-chave por intenção de busca (PT-BR)
*Método: autocompletar do YouTube no Brasil (`suggestqueries`, ds=yt, hl=pt-BR, gl=BR), consultado em 11/10/2026. O autocompletar mostra **o que as pessoas digitam, não volume**. Para comparar a demanda, use o Google Trends (grátis, https://trends.google.com/trends/explore?geo=BR&q=gta%206) e o relatório "Pesquisa" do Studio quando houver dados.*

| Intenção | Sugestões reais do autocompletar | Pacote correspondente |
|---|---|---|
| Data e lançamento | "gta 6 quando lança", "gta 6 quando sai", "gta 6 data de lançamento 2026" | Guia Oficial: data e horário |
| Plataforma e console | "gta 6 vai sair para ps4", "gta 6 vai rodar no xbox series s", "gta 6 ps5 ou ps5 pro", "gta 6 pc requisitos", "gta 6 pc 2027" | Guia Oficial: consoles e PC (responder "não anunciado" quando for o caso) |
| Idioma | "gta 6 vai ser dublado", "gta 6 dublado em português brasileiro", "gta 6 legendado" | Guia Oficial: idiomas (com print da PS Store) |
| Preço e compra | "gta 6 preço", "gta 6 pré venda" | GTA VI no Brasil: preço e edições |
| Mundo e conteúdo | "gta 6 mapa oficial", "gta 6 tamanho do mapa", "gta 6 vice city", "gta 6 personagens", "gta 6 lucia e jason", "gta 6 todos os carros", "gta 6 policia" | Leonida Explicada / Personagens / Raio-X |
| Material oficial | "gta 6 trailer 3", "gta 6 extended look", "gta 6 musicas" | Raio-X Oficial (análise, nunca reenvio) |
| Pós-lançamento (como fazer) | "gta 6 como jogar", "gta 6 como ganhar dinheiro", "gta 6 online como será" | Primeiras Horas (só depois de 19/11 e com o jogo em mãos) |
| **Evitar** (intenção de vazamento ou pirataria) | "gta 6 vazamento", "gta 6 leak", "gta 6 apk obb", "gta 6 como baixar", "gta 6 map mod" | Não produzir. Nunca usar como tag ou título |

**Regras de metadados para busca:**
- A palavra-chave principal vai no **início do título** ("GTA 6: …") e na **1ª frase da descrição**.
- **Capítulos** em todo vídeo longo: a descrição começa em `00:00`, tem pelo menos 3 marcações em ordem crescente e cada capítulo dura pelo menos 10 s (https://support.google.com/youtube/answer/9884579). O título de cada capítulo é uma pergunta buscável, por exemplo "GTA 6 tem dublagem?".
- Até 3 a 5 hashtags. Mais de 60, o YouTube ignora todas (https://support.google.com/youtube/answer/6390658).
- Legenda `.srt` revisada enviada ao YouTube (acessibilidade e texto indexável).
- **Vídeos perenes ganham "versão atualizada":** quando um dado oficial muda (preço, PC, patch), crie um pacote de atualização com título "(atualizado DD/MM)" e corrija descrição e fixado. Não reenvie o mesmo vídeo.

### 4.3 Estrutura de playlists e funil interno
- Playlists na ordem das séries do §4.1. O vídeo de entrada de cada playlist é o mais amplo, por exemplo "GTA 6: tudo que é oficial até agora".
- **Tela final:** sempre aponta para o próximo vídeo da mesma série. **Cartão** no ponto em que o assunto puxa outro vídeo.
- **Shorts → longo:** todo corte usa "Vídeo relacionado" apontando para o vídeo longo de origem (https://support.google.com/youtube/answer/14075157).
- Comentário fixado: resumo com fontes. Se houver link de afiliado, começa com "#publi".

---

## 5. Calendário de PRODUÇÃO da janela de lançamento (19/11/2026)
*São prazos de **entrega do pacote pronto**, não datas de publicação. O Luiz publica quando quiser, dentro da validade.*
*Datas oficiais: pré-carga e mídia física em 12/11, lançamento em 19/11 (https://taketwointeractivesoftwareinc.gcs-web.com/news-releases/news-release-details/rockstar-games-announces-pre-orders-grand-theft-auto-vi).*

| Entrega até | Pacote (longo + cortes) | Série | Validade / gatilho |
|---|---|---|---|
| 14/10 | **Vídeo A**: "GTA 6: o que 27 minutos realmente revelaram sobre como o jogo funciona" + 3 cortes | Raio-X Oficial | Perene |
| 17/10 | "GTA 6: data, horário e plataformas, tudo que é oficial" + 3 cortes | Guia Oficial | Revisar se houver anúncio oficial |
| 21/10 | "GTA 6 no Brasil: preço, edições e idiomas (PS Store e Xbox)" + 3 cortes | GTA VI no Brasil | Checar o preço na loja antes de liberar. Validade até 18/11 |
| 24/10 | "GTA 6 vai sair pra PS4 ou PC? A resposta oficial" + 2 cortes | Guia Oficial | Revisar se a Rockstar anunciar PC |
| 28/10 | "Lucia, Jason e o elenco: tudo que a Rockstar mostrou" + 3 cortes | Personagens Oficiais | Perene (sem spoiler) |
| 31/10 | "Vice City e Leonida: as regiões mostradas oficialmente" + 3 cortes | Leonida Explicada | Perene |
| 04/11 | "GTA V x GTA VI: o que mudou na polícia (material oficial)" + 3 cortes | GTA V x GTA VI | Perene |
| 08/11 | "Pré-carga de GTA 6: passo a passo no PS5 e no Xbox" + 2 cortes | GTA VI no Brasil | Publicar a partir de 12/11, ou antes como "como se preparar". Validade até 25/11 |
| 15/11 | "GTA 6: checklist oficial para o dia do lançamento" + 2 cortes | Guia Oficial | Validade até 19/11 |
| Sob gatilho | "Confirmado pela Rockstar: [anúncio]" + 1–2 cortes (pronto em até 24 h) | Confirmado | **Só se** houver comunicado oficial (Newswire, X da Rockstar, Take-Two). Validade de 3 dias |
| 20–23/11 | "Primeiras horas em GTA 6: o que fazer primeiro (sem spoiler)" + 3 cortes | Primeiras Horas | Perene (gameplay próprio narrado) |
| 24–30/11 | "Como ganhar dinheiro no começo de GTA 6" e "Configurações recomendadas" + cortes | Primeiras Horas | Perene, atualizar com patches |
| Dezembro | Guias pós-lançamento conforme as perguntas reais (autocompletar e comentários) | Primeiras Horas / Guia Oficial | Perene |

*Capacidade:* cerca de 2 pacotes longos por semana até 19/11. Se a revisão humana virar gargalo, a prioridade é qualidade: cortar a quantidade, nunca o checklist.

---

## 6. Reciclagem profissional multiplataforma

### 6.1 Políticas que mudam o jeito de reaproveitar
| Plataforma | Regra oficial | Fonte |
|---|---|---|
| YouTube | Políticas de conteúdo reutilizado e não original (§3.2–3.3). Shorts com até 3 min | https://support.google.com/youtube/answer/1311392?hl=pt-BR · https://support.google.com/youtube/answer/15424877 |
| TikTok | Conteúdo reproduzido ou não original, **incluindo vídeos importados de outra plataforma com marca d'água ou logo**, pode ficar fora do "Para Você". O feed não recomenda duplicatas | https://www.tiktok.com/community-guidelines/en/fyf-standards · https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you |
| Instagram Reels | Só conteúdo elegível vai para recomendação: original e **sem marca d'água visível**. Quando há conteúdo idêntico, só o original é recomendado. Borda, legenda na mesma língua do áudio, logo e crédito contam como edição "mínima" para conteúdo de terceiros | https://creators.instagram.com/blog/recommendations-and-originality · https://www.facebook.com/business/help/1110625196872995 |
| Facebook Reels | Repostagem repetida de conteúdo alheio perde monetização e alcance. Duplicatas têm distribuição reduzida. Meta recomenda evitar marcas d'água de terceiros | https://creators.facebook.com/blog/combating-unoriginal-content/ · https://www.facebook.com/business/help/262834734651607 |

**Regras de reciclagem:**
1. Exportar **um arquivo limpo por plataforma** a partir do projeto. **Nunca** baixar um vídeo do TikTok ou do CapCut com marca d'água para repostar.
2. O conteúdo é **nosso** (roteiro, narração, edição), então o mesmo corte pode ir para todas as redes. Mesmo assim, cada rede ganha **legenda escrita, hashtags e CTA próprios**, e o TikTok pode receber uma versão maior (veja abaixo).
3. Nunca postar o mesmo corte duas vezes na mesma plataforma. Para testar outro gancho, **reedite** (abertura nova). No Instagram, use Trial Reels para testes.
4. Cada vídeo de 20–25 min gera **até 3 cortes com ângulos diferentes**: dado, pergunta e comparativo. Cada corte se sustenta sozinho e tem narração própria no começo.

### 6.2 Adaptação por plataforma
| | YouTube Shorts | TikTok | Instagram Reels | Facebook Reels |
|---|---|---|---|---|
| Duração-alvo | 20–60 s (até 3 min) | 60–90 s quando houver conteúdo (o Programa de Recompensas exige pelo menos 1 min). Senão 20–60 s | 20–60 s | 20–60 s (pelo menos 10 s se entrar no programa de monetização; não verificado no detalhe) |
| Ligação com o longo | "Vídeo relacionado" com o longo | "Vídeo completo no YouTube: BR no GTA" na legenda | Link na bio + CTA falado | Compartilhar do Instagram ou enviar o arquivo limpo |
| Legenda e hashtags | Título com palavra-chave + 3 hashtags | Legenda com palavra-chave + 3–5 hashtags | Até 5 hashtags (limite do app) | 2–3 hashtags |
| Rótulo de IA | "Uso de IA" no Studio | Rótulo "conteúdo gerado por IA" | Rótulo de IA da Meta | Rótulo de IA da Meta |
| #publi | 1ª linha + "promoção paga" | 1ª linha (e a ferramenta de conteúdo comercial do app) | 1ª linha da legenda (+ "parceria paga" quando for parceria com marca) | 1ª linha |

### 6.3 Pipeline open source (custo zero)
**Ferramentas:**
- **FFmpeg** (corte, reenquadramento, legendas embutidas, áudio): https://ffmpeg.org
- **WhisperX** (transcrição com tempo por palavra, licença BSD-2): https://github.com/m-bain/whisperX. Para português, use `--language pt`. **Confira a licença do modelo de alinhamento** antes de uso comercial; o projeto avisa que alguns modelos padrão são "não comercial" (https://github.com/m-bain/whisperX/issues/962).
- Edição: Kdenlive ou Shotcut. Thumbnail: GIMP ou Krita. Fonte de legenda com licença OFL (por exemplo, Montserrat).

**Comandos de referência:**
```bash
# 1) Corte do master (substitua os tempos)
ffmpeg -ss 00:12:30 -to 00:13:20 -i master_16x9.mp4 -c:v libx264 -crf 18 -preset slow -c:a aac -b:a 192k corte.mp4

# 2) Reenquadrar para 9:16 (1080x1920). X_OFFSET escolhe a área: centro = (iw-ih*9/16)/2
ffmpeg -i corte.mp4 -vf "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos" -c:v libx264 -crf 18 -c:a copy corte_9x16.mp4
#    Se o assunto se mover, divida em trechos com X_OFFSET diferentes (ou use um gráfico próprio em vez do frame original)

# 3) Transcrever com tempo por palavra (gera .srt)
whisperx corte.wav --model large-v3 --language pt --output_format srt --output_dir legendas/

# 4) Revisar o .srt à mão (nomes: Lucia, Jason, Leonida, Vice City) e depois embutir
ffmpeg -i corte_9x16.mp4 -vf "subtitles=legendas/corte.srt:force_style='FontName=Montserrat,FontSize=16,Bold=1,Outline=3,Alignment=2,MarginV=260'" -c:v libx264 -crf 18 -c:a copy corte_final.mp4

# 5) Normalizar volume da narração + Hazewave (dois passes do loudnorm para mais precisão)
ffmpeg -i corte_final.mp4 -af loudnorm -c:v copy corte_final_norm.mp4
```

**Regras de enquadramento e legenda:**
- Texto e legenda **longe das bordas de baixo e da direita** (onde ficam os botões dos apps). Confira em cada app antes do primeiro lote; as plataformas não publicam uma "zona segura" única.
- Legenda **revisada por humano**: erro de nome de personagem derruba a credibilidade de um canal "oficial".
- O próprio repositório tem um motor de vídeo (`video-engine/`, com captions e effects). Esses comandos são o equivalente manual e servem de alternativa.

---

## 7. Loja de afiliados (produtos oficiais/licenciados ou genéricos gamer)

### 7.1 Programas e requisitos
| Programa | Requisitos e regras | Fonte |
|---|---|---|
| **Shopee Afiliados** | 18 anos ou mais, CPF, sem mínimo de seguidores. **Proibido divulgar produto proibido, ilegal ou falsificado, ou que viole marca ou direito de terceiros.** Violação pode suspender ou encerrar a conta. Proibido também comprar anúncio com a marca Shopee e enviar spam (ver plano de renda) | https://help.shopee.com.br/10/article/124094-Programa-de-Afiliados-Shopee-Termos-e-Condi%C3%A7%C3%B5es · https://help.shopee.com.br/10/article/163025 |
| **TikTok Shop afiliado (BR)** | 18 anos ou mais e 1.000 seguidores, com verificação de identidade (fontes secundárias). Política de propriedade intelectual: **proibido falsificado, "réplica", "dupe" ou "parecido com"**, logo escondido ou alterado e hashtag de marca sem autorização | https://seller.tiktok.com/br · requisitos (secundária): https://www.ihubcreators.com.br/tiktok-shop/requisitos-tiktok-shop · política (EUA, referência): https://seller-us.tiktok.com/university/essay?knowledge_id=5090656611682090&lang=en |
| **Instagram** | Link de afiliado da Shopee na bio, em Stories com link e na legenda. Sem mínimo de seguidores | Regras de identificação: CONAR (abaixo) |
| **YouTube Shopping afiliados** | Só no YPP com mais de 5.000 inscritos. Fica para depois | https://blog.youtube/intl/pt-br/news-and-events/yt-shopping-afiliados-brasil/ |

### 7.2 O que pode e o que não pode
**Pode:**
- **Produtos oficiais ou licenciados vendidos por loja oficial ou autorizada** (selo de loja oficial, nota fiscal): o próprio jogo em mídia física ou digital, consoles, controles oficiais (DualSense, controle Xbox), headsets de marca, SSD compatível com PS5 e Xbox, cartão-presente PSN/Xbox de vendedor oficial.
- **Acessórios gamer genéricos sem marca de terceiros:** suporte e carregador de controle, cadeira, mesa, iluminação, cabo HDMI, organizador, grip.

**Nunca:**
- Produto com **logo ou nome GTA, Rockstar, Vice City ou Leonida** que não seja comprovadamente licenciado (o X tem anúncios de "suporte de controle GTA 6", por exemplo). Na dúvida, não divulgue. O merchandising oficial de GTA VI é vendido pela loja da Rockstar (store.rockstargames.com); a entrega no Brasil não foi verificada.
- Keys ou contas "baratas", "dinheiro do jogo", contas modificadas, mod menu, "GTA 6 APK", desbloqueio, pirataria.
- Linguagem enganosa: "o mesmo da Rockstar", "réplica", "igual ao original" e afins.

**Na prática:** a página do produto vai em `content/videos/<pacote>/afiliados.md` com link, vendedor, selo de loja oficial (sim ou não) e print. Um produto que não passa nessa checagem não entra no pacote.

### 7.3 Categorias por pauta (casar produto com conteúdo, sem forçar)
| Pauta | Categoria |
|---|---|
| Pré-carga e espaço em disco | SSD M.2 compatível com PS5 e HD externo (verificar compatibilidade oficial) |
| Configurações e imagem | Cabo HDMI 2.1 e suporte de TV/monitor (genérico) |
| Dia do lançamento e maratona | Headset, carregador ou base de controle genéricos e cadeira |
| Comprar o jogo | Mídia física (só loja oficial ou autorizada) e cartão-presente PSN/Xbox oficial |

### 7.4 Identificação (CONAR) e onde colocar o link
**O que diz o CONAR:** link de afiliado, cupom ou link rastreável que dá comissão é **publicidade** e precisa de identificação clara. Use a ferramenta da plataforma ou **#publi / #publicidade**, visível **logo de cara**, sem depender de "mais", de rolar a tela ou de clique.
http://conar.org.br/pdf/260525_GUIA_INFLUENCIADORES_CONAR_v6.pdf · tabela de expressões: http://www.conar.org.br/pdf/Tabela-para-Influenciadores-Expressoes-de-Identificacao-publicitaria.pdf · Shopee: https://help.shopee.com.br/10/article/196794
**No YouTube:** marcar "Inclui promoção paga" (https://support.google.com/youtube/answer/154235).

| Onde | Como |
|---|---|
| Descrição do YouTube | **1ª linha:** `#publi Links de afiliado (ganho comissão se você comprar): ...` e depois os links. O vídeo vem logo abaixo, com a palavra-chave |
| Comentário fixado | `#publi` + o link do produto citado no vídeo |
| Dentro do vídeo | Aviso falado + texto na tela "#publi, link de afiliado" quando o produto aparecer. Caixa "promoção paga" marcada |
| TikTok | `#publi` no início da legenda, ferramenta de conteúdo comercial ligada e link do TikTok Shop (quando liberado) |
| Instagram e Facebook | `#publi` no início da legenda + link na bio. Em Stories com link, adesivo "#publi" visível |
| Vídeos sem produto | Sem link e sem #publi. Não force afiliado em pauta que não pede |

---

## 8. Organização de pastas (mapeada no repositório, sem alterar o GitHub)
*É só uma proposta. Nada foi modificado em `zenindiones-maker/BR-no-GTA` (cópia local em `/workspace/br`, commit `8c1743aa`).*
```text
brain/
  radar/       comunicados OFICIAIS da semana (Newswire, Take-Two, lojas): só fontes da lista §1
  ideas/       pautas candidatas, cada uma com série, intenção de busca e fonte oficial
  scoring/     notas da skill gta6-editorial
  knowledge/   base de fatos oficiais (fato, URL, data, validade) + políticas (§3)
  analytics/   exportações das APIs (YouTube Analytics/Reporting, Instagram, TikTok)
  memory/      últimos ganchos e estruturas (anti-repetição, §3.2) e aprendizados
  archive/     pacotes vencidos ou recusados
content/
  research/    dossiê de cada pacote (ex.: video-a-extended-look-editorial-package-v2.json)
  scripts/     roteiros longos e de cortes
  videos/      <AAAA-MM-DD>-<slug>/  = PACOTE PRONTO (estrutura do §2.2, com PUBLICAR.md)
  shorts/      cortes avulsos que não vêm de um longo (raro), mesma estrutura de LEIA.md
YouTube/
  scripts/     coleta de métricas e upload privado opcional
  logs/        registros (sem tokens ou credenciais)
```

## 9. Métricas (coleta gratuita, sem horário obrigatório)
Como o Luiz publica em horários livres, **compare cada vídeo com a mediana dos vídeos do mesmo formato**, não com dia e hora.
- **YouTube Analytics API:** views engajadas, tempo de exibição, % médio assistido, retenção e fontes de tráfego (inclusive "Pesquisa no YouTube", o termômetro da autoridade de busca). https://developers.google.com/youtube/analytics/metrics
- **YouTube Reporting API:** impressões e CTR. https://developers.google.com/youtube/reporting/v1/reports/channel_reports
- **Instagram:** views, alcance, envios e tempo médio. https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights/
- **TikTok:** views, curtidas e compartilhamentos. https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query
- **Saúde do canal:** ícones amarelos, reivindicações, avisos de conteúdo não original e status da conta no Instagram e no Facebook.
- **Busca:** termos de pesquisa por vídeo, para alimentar novos pacotes do Guia Oficial.

## 10. Pendências e pontos não verificados
- A Rockstar autoriza oficialmente só uso **não comercial**. Monetizar GTA tem tolerância de fato, não garantia (§3.7).
- O processo de Content ID e a liberação de canal na distribuidora do Hazewave dependem da distribuidora escolhida.
- O TikTok Shop BR tem requisitos de fontes secundárias. Confira no app ou em seller.tiktok.com/br.
- O mínimo de 10 s nos Reels do Facebook para monetização não foi verificado no detalhe.
- A entrega da Rockstar Store no Brasil não foi verificada.
- Confira na loja o preço e os idiomas na PS Store e na Xbox antes de liberar cada pacote.
- A data de lançamento é a oficial de hoje. Qualquer mudança só entra por comunicado oficial.
