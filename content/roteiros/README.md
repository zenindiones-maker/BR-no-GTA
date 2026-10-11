# content/roteiros — fonte única de roteiros (diretriz do Luiz, 11/10/2026)

Regra: **um vídeo por vez, cada vídeo com roteiro próprio, e vídeo só sai de roteiro
aprovado.** Nenhum render começa sem passar por `scripts/script_first_gate.py`.

## Estrutura

```
content/roteiros/<script_id>/
  roteiro.md      texto final da narração (PT-BR)
  roteiro.json    metadados (schema br-roteiro/v1)
  aprovacao.md    registro humano da aprovação do Luiz (quem, quando, sha256)
  originalidade.json  saída do gate (reuso máximo vs roteiros anteriores)
```

`_modelo/` é um exemplo e é ignorado pelo gate.

## Estados (`roteiro.json.status`)

| de | para | quem |
|---|---|---|
| rascunho | editorial_ok | só o agente editorial (`GTA6 Master Agent` / `br_editorial_process_next`) |
| editorial_ok | aprovado_humano | só o **Luiz**, com data e sobre o mesmo sha256 |
| aprovado_humano | em_producao | orquestrador, quando o render começa |
| em_producao | entregue | após QA e PUBLICAR.md prontos em `content/videos/<slug>/` |
| qualquer | rejeitado | editorial ou Luiz |

Implementado em `scripts/script_first_gate.py::transition`.

## O que o gate exige antes do render

1. `script_id` e `script_sha256` informados (render-worker tem esses inputs obrigatórios).
2. sha256 do texto normalizado == `roteiro.json.sha256` == `approval.approved_sha256`.
3. status `aprovado_humano` (ou `em_producao` do próprio roteiro) e `approved_by: Luiz`.
4. `author_agent` é o agente editorial.
5. pelo menos uma fonte oficial (rockstargames.com / take2games.com). Sem vazamento, sem especulação.
6. nenhum outro roteiro em `em_producao` (um vídeo por vez).
7. originalidade: sha diferente e reuso de 8-gramas ≤ 5% contra todo roteiro já aprovado/produzido/entregue
   (`app/services/editorial_novelty_service.py`).

Checkpoints de retomada só são aceitos se carregarem o mesmo `script_id`/`script_sha256`.

## Pacote de publicação

Quando o vídeo é entregue, `roteiro.json.package` aponta para `content/videos/<slug>/PUBLICAR.md`
(modelo em `content/videos/_modelo_pacote/`). O clique de publicar é sempre do Luiz.
