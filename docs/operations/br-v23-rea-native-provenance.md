# BR-no-GTA — REA próprio, proveniência V1/V3/V4 e reconciliação V23

**Estado:** inventário versionado, observação e diagnóstico apenas. **Autoridade:** DeepSeek Harness do BR-no-GTA. Esta política não promove componentes antigos automaticamente e não substitui os requisitos do `AGENTS.md`.

## 1. Origem comprovada no próprio repositório

O BR-no-GTA **já possui REA e Harness de engenharia reversa**, antes da branch V23 atual. Esses componentes não podem ser descartados só porque não constam de um checkout de recuperação mais recente.

| Linha BR | HEAD remoto observado | Evidência / capacidade |
| --- | --- | --- |
| `work/br-extreme-reverse-engineering-v1` | `ea48884eacd7532122485929da91c2865ab02377` | `integrations/rea`, `integrations/rea_install_and_doctor.sh`, serviços de REA/forense/mídia/roteiro, `scripts/br_reverse_engineering_harness.py`, workflow próprio |
| `work/br-reverse-engineering-evidence-v3` | `f13ef0a5dd02d3417aa4ccc58ed1c5c3a9b0ba95` | áudios, cenas, longform e web HAR medidos sob Harness |
| `work/br-reverse-engineering-experiment-intelligence-v4` | `ad00c215ecd33ee74703cfeb0d72694220b666f0` | avaliação experimental, casos pareados e holdout, sem auto-promoção |

A integração original usa o upstream público `https://github.com/morluto/rea.git`, módulo Git `integrations/rea` e o pacote exato `rea-agents@6.0.0`, subordinados ao **DeepSeek Harness**. Os padrões de licença, hash, risco de supply-chain e versões devem ser revalidados antes de qualquer uso novo.

O workflow nativo BR `.github/workflows/br-reverse-engineering-plane.yml` em V4 teve `SUCCESS` no commit `ad00c215ecd33ee74703cfeb0d72694220b666f0`, run `37783345160`. Logs verificaram 95 testes, REA CLI, Harness com objeto autoritativo, análise real de FFmpeg e experimentos conservadores.

Referência auditável:
`https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37783345160`

## 2. Situação da branch de recuperação V23

Branch `work/br-v23-actions-contract-recovery-v1` preserva o código de Owner Voice V23 e controles de segurança. A árvore original inspecionada nesta linha **não incluía os serviços nativos da REA V4 nem o submódulo**. Isso significa **não integrado ao checkout V23**, **não inexistente no BR-no-GTA**. A presença de uma instalação REA no Codespace V23 também não foi medida diretamente: **ON_HOST_INSTALL=UNVERIFIED**.

Foi executado ainda um estudo independente e restrito do frontend *do próprio BR* com `rea-agents@6.0.0` em um runner temporário:
- Workflow: `.github/workflows/br-v23-rea6-frontend-research.yml`
- Run `37874845896`: `SUCCESS`, `REA6_REAL_CLI_INVOCATION=PASS`, `BR_REA6_JS_EVIDENCE_GRAPH=PASS`
- Alvo: `video-engine/frontend`, exclusivamente código do próprio BR
- `169` módulos JS, `220` nós no grafo, saída de `93,409,719` bytes
- SHA256 da saída REA: `6f34be3aa95a6eb4b316e0d786050c584ea4f0a3290d61730ba6867da1f6f2f1`
- **Não provou**: Ghidra, análise nativa, MCP ligado a agente real, bugs corrigidos, equivalência de comportamento, inferência de voz ou qualidade de produção.

Referência auditável:
`https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37874845896`

## 3. Regra de reconciliação sem importar arquitetura

1. Continuar somente no repositório `zenindiones-maker/BR-no-GTA`. **Não importar código, agentes, skills, configurações, regras de autoridade ou evidências de projetos externos.**
2. Conferir a identidade Git, branch e HEAD dos candidatos V4 e V23. Consultar `AGENTS.md` de cada revisão; o Harness V23 governa operações V23.
3. Ler os serviços `reverse_engineering_*` do histórico BR V4 e comparar suas dependências reais com o V23 atual. Marcar `EXISTING`, `MISSING`, `CONFLICT`, `API_DRIFT` e `UNVERIFIED` por componente.
4. Não `git switch` sobre o checkout com WIP nem `reset --hard`, `force-push`, merge direto, substituição de arquivos deletados ou ressurreição automática de arquitetura obsoleta. Usar worktree/ref isolado quando necessário, após verificar integridade e recursos disponíveis.
5. REA software, FFmpeg mídia, Qwen voz e identidade `BR_OWNER_V1` são disciplinas distintas. Não deixar o REA aprovar voz/clonagem, controlar Telegram ou autorizar publicação.
6. Execuções e instalações **somente remotas**, com teto de memória, tempo e cota conhecida. A15 é apenas controle.
7. O diagnóstico completo exige provas específicas por rota: arquivos e sintaxe, JS real, mídia real, código nativo/Ghidra se houver, vulnerabilidades, runtime, contratos Harness, e avaliação independente. `CI SUCCESS` em uma rota nunca equivale a aprovação total.

## 4. Estado para seguir

- `BR_OWN_REA_HISTORY=VERIFIED`
- `V4_NATIVE_HARNESS_CI=SUCCESS` (runner remoto da época)
- `V23_OWN_JS_REA6_CI=SUCCESS` (runner remoto atual)
- `V23_REA_NATIVE_HARNESS_INTEGRATED=NOT_PROVEN`
- `V23_CODESPACE_REA_INSTALLED=NOT_VERIFIED`
- `GITHUB_CANONICAL_PROMOTION=NOT_ATTEMPTED`
- `OWNER_VOICE_MODEL_RUN=NOT_ATTEMPTED`
- `FULL_REVERSE_ENGINEERING_OF_ALL_FUNCTIONALITY=NOT_PROVEN`

Reconciliar o **REA já existente do BR**, não criar um segundo Harness nem abandonar linhas de desenvolvimento válidas.
