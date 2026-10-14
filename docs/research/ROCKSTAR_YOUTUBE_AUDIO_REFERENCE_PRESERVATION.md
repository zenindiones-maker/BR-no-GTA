# Preservação — referências acústicas Rockstar / GTA (PT-BR)

Status: registro de preservação criado em 2026-10-13. Não declarar os áudios binários recuperados até verificar os arquivos.

## Objetivo

Preservar o trabalho de engenharia reversa acústica da pronúncia Rockstar/GTA, mantendo separadas:
- referências públicas de áudio/vídeo do YouTube usadas como referência máxima;
- dicionário de pronúncia e evidências;
- áudios de teste gerados para BR_OWNER_V1 (não são referências Rockstar).

## Referências YouTube a reconciliar

Estes dois IDs aparecem no contexto histórico do projeto como referências de dublagem PT-BR. A metadata não pôde ser reconsultada nesta execução; confirmar título/canal e se são exatamente o par de referência máxima antes de marcar como verificados.

- https://www.youtube.com/watch?v=f8IZhKcuEts
- https://www.youtube.com/watch?v=K6rVM6gn6k4

Não há, neste registro, prova de que os arquivos de áudio originais desses vídeos estejam atualmente guardados no repositório ou nos artefatos listados abaixo. Não substituir por outros vídeos nem por áudio sintético.

## Trabalho textual já rastreado no repositório

Os seguintes arquivos existem no ramo de trabalho de origem e devem ser mantidos:
- `config/pronunciation_ptbr_research.json`
- `config/pronunciation_ptbr_candidate.json`
- `config/pronunciation_evidence_registry.json`
- `config/pronunciation_lexicon.json`
- `config/pronunciation_golden_ptbr.json`
- `config/pronunciation_human_approvals.json`
- `config/pronunciation_ptbr_policy.json`
- `app/services/pronunciation_service.py`
- `scripts/video_a_audio_forensics.py`
- `scripts/video_a_audio_forensics_v2.py`
- `scripts/semantic_ptbr_audio_qa.py`

A pesquisa registra 47 termos; somente 2 aparecem como acusticamente validados e aprovados por humano no snapshot analisado. Não interpretar cobertura de pesquisa como validação acústica.

## Artefatos temporários do GitHub Actions — preservar antes da expiração

Repositório: `zenindiones-maker/BR-no-GTA`

| Run | Artifact ID | Nome | Expira |
|---|---:|---|---|
| 35527492016 | 10610442121 | `video-a-narration-readiness-35527492016` (~82.5 MB) | 2026-10-20 18:04:26 UTC |
| 35529067781 | 10610666993 | `video-a-audio-forensics-35529067781` | 2026-10-20 18:29:39 UTC |
| 35529442264 | 10610528309 | `video-a-corrected-pronunciation-inventory-35529442264` | 2026-10-20 18:33:35 UTC |

A documentação de forense associa o primeiro artefato a material de audição/áudio gerado e o segundo ao relatório de forense. Nenhum deles foi confirmado como contendo os dois áudios originais do YouTube. Baixar e listar os ZIPs antes de expirar; preservar os originais em armazenamento durável permitido, com URL, título, canal, data de captura, hash SHA-256 e licença/origem. Não colocar áudio biométrico privado do proprietário no repositório público.

## Próximas verificações obrigatórias

1. Baixar os três artefatos listados acima antes de 2026-10-20.
2. Inspecionar o conteúdo dos ZIPs; distinguir arquivos fonte do YouTube de áudios derivados/sintéticos.
3. Localizar ou baixar novamente os dois vídeos de referência a partir dos URLs acima, respeitando disponibilidade e direitos aplicáveis.
4. Registrar SHA-256, duração, codec, sample rate, canal e proveniência de cada arquivo recuperado.
5. Atualizar `config/pronunciation_evidence_registry.json` somente com evidência verificada; não promover candidatos a aprovação humana sem escuta/validação.
