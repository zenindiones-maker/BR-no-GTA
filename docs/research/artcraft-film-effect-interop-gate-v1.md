# BR-no-GTA — FilmCraft + EffectCraft, interoperabilidade isolada V1

Status: **implementação de contrato + linha de base audiovisual**. Não é integração de produção, não inicia agentes, não executa código Adobe e não constitui certificação do renderizador nativo.

## Evidência de código upstream (commits fixados)

| Projeto | SHA do código-fonte | Interface observada |
|---|---|---|
| FilmCraft | `7b6c134472287db4367fca80bcb498240ba36567` | `apps/filmcraft-cli/src/main.rs`: `--demo render --seconds 0 --out frame.png --scale 0.16`; `crates/render/src/lib.rs`: `render_sequence` |
| EffectCraft | `30aaddf7c23329dcdfc72a5bf65b55747bbd6be1` | `apps/effectcraft-cli/src/main.rs`: `render-frame --demo --frame 0 --max-side 320 --out frame.png --json`; `crates/render/src/lib.rs`: `render_frame` |

Ambos usam `TICKS_PER_SECOND = 254016000000` em `crates/time/src/lib.rs`. Para 30 fps, cada frame avança **8.467.200.000 ticks**; para 29,97 (30000/1001) o avanço é **8.475.667.200 ticks**. A coincidência de escala de tempo não implica compatibilidade dos modelos de projeto, binários ou cenas.

## Código desenvolvido nesta candidata

- `scripts/artcraft_film_effect_interop.py` é o único ponto de contrato e não importa bibliotecas de terceiros. Define comandos nativos fixos sem acesso a `script`, `mcp`, `exec`, rede ou ferramentas genéricas; exige caminho de binário, SHA256 de cada binário e declaração explícita de sandbox externo, mas **essa declaração não comprova isolamento**.
- `scripts/artcraft_make_synthetic_interop_fixtures.py` gera cinco imagens RGB 320×180, um alpha RGBA, áudio WAV estéreo e MP4 sintético de 5s (150 frames H.264 yuv420p + AAC 48k).
- `tests/test_artcraft_film_effect_interop.py` exercita 15 contratos de fonte, tempo, integridade, FFprobe, corrupção de dados, symlink, erro de binário e montagem de argv com **CLIs simulados**.
- `.github/workflows/br-artcraft-film-effect-interop-probe.yml` executa os testes, decodifica mídia sintética de verdade com FFmpeg e preserva `receipt.json` em artefato de 30 dias, explicitamente marcado `BASELINE_ONLY`.

O gate `BASELINE_ONLY` **NÃO** significa que os CLIs reais executaram. `NATIVE_CLI=NOT_EXECUTED` e `production_approved=false` devem permanecer até nova prova controlada com builds verificáveis.

## Dependências e autorização futura para prova nativa

1. Concluir o build dos binários reais de `filmcraft-cli` e `effectcraft-cli`, fixando commit upstream, Cargo.lock, Rust toolchain e SHA256 do artefato.
2. Executar os dois comandos acima em um **contêiner independente com rede desligada, usuário não privilegiado, capabilities eliminadas e ausência de secrets**, não diretamente no runner/host. O atributo `ARTCRAFT_EXTERNAL_NETWORK_SANDBOX=CONFIRMED` é apenas indicação do chamador; **não** substitui o controle na camada de execução.
3. Verificar PNG integral, dimensões, transparência, tempos, não-vazamento de arquivo, performance, repetibilidade e saída após falha/cancelamento. Os demos dos dois programas produzem imagens diferentes: não comparar pixels como se as cenas fossem a mesma.
4. Só depois estudar um adaptador de troca de arquivos, sem conectar MCP nem conceder autoridade ou acesso ao VEdit/FFmpeg de produção. `EffectCraft` utiliza 16 dependências Git de outro commit do FilmCraft: não substituí-las silenciosamente.
5. Para produção BR-no-GTA, exigir prova adicional 1920×1080 30 fps H.264 High yuv420p + AAC, 20–25 minutos com conteúdo editorial real **sem padding**, e aprovação humana da voz `BR_OWNER_V1` e publicação.

## Limites de segurança

Esta candidata NÃO altera `main`, V24, o DeepSeek Harness, políticas de Owner Voice, Telegram, YouTube, Media Worker, código upstream ou o A15. Não faz instalação permanente, merge, deploy, gastos, novos Codespaces ou promoção. A aprovação de uma linha de base FFmpeg não comprova que o FilmCraft ou EffectCraft estão instalados ou operacionalmente integrados.

Executar o workflow na branch `work/br-artcraft-film-effect-interop-v1`. Revisar conclusões e SHA exato. A branch matriz dos sete fontes permanece isolada em `work/br-artcraft-seven-source-study-v1`.
