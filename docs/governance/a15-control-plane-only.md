# A15 CONTROL PLANE ONLY — Política permanente de execução remota

**Estado:** Diretriz expressa do proprietário, obrigatória para todas as operações
do BR-no-GTA. **Abrangência da preferência do proprietário:** também se aplica aos
projetos HAZEWAVE/HAZE/WAVE; a incorporação técnica nos demais repositórios
depende de alteração autorizada e independente.

**Autoridade:** Proprietário → DeepSeek Harness → executores subordinados.
Este documento **não** cria uma segunda autoridade, não altera as políticas de
segurança existentes, não concede custos, e não autoriza processamento privado,
clonagem, promoção ou publicação.

## 1. Regra principal — sem exceção implícita

O Samsung A15 com Termux é **apenas um terminal de comando e controle**.
**NÃO** é estação de desenvolvimento, inferência, treinamento, edição,
renderização ou armazenamento de trabalho. Nenhuma implementação nova pode
transferir processamento ou dados pesados para o A15 por conveniência.

A15 **permitido** (controle leve):
- SSH e sessões remotas, autenticação, `gh codespace ssh/list/stop`, consultas
  a GitHub Actions, comandos Git *somente para controle já existente*, leitura
  pontual de status, logs e recibos, e supervisores/gateways previamente
  autorizados com consumo leve;
- encaminhar instruções do proprietário a workstations, GitHub Actions,
  Codespaces e outras máquinas remotas autorizadas;
- preservar os scripts e serviços de controle que já funcionam no Termux.

A15 **proibido** (não executar, não instalar, não armazenar):
- Qwen3-TTS, PyTorch, Whisper, modelos, pesos, fine-tunes, embeddings ou
  avaliação de identidade vocal;
- FFmpeg de produção, renderizações, codificação, áudio/vídeo de trabalho,
  datasets, arquivos privados de voz, checkpoints de modelo, caches de modelos
  e artefatos volumosos;
- `pip install`, `pkg install`, `apt install`, containers ou runtimes
  para habilitar qualquer carga de processamento ou edição no telefone;
- baixar/transmitir amostras privadas para o telefone como staging temporário;
- instalar ferramentas novas mesmo leves sem necessidade de controle
  comprovada e aprovação explícita do proprietário.

**Exceção explícita:** só uma instrução posterior e inequívoca do proprietário
pode autorizar uma alteração *pontual*; não interpretar um objetivo genérico
como permissão de instalar ou computar no A15.

## 2. Destino das cargas de trabalho

- **Codespaces / workstations Linux**: código, testes, Python, FFmpeg, QA,
  análise, arquivos intermediários e tarefas autorizadas dentro da cota.
- **GitHub Actions**: CI e jobs delimitados por tempo, recursos, política,
  evidências verificáveis e restrições de segredo.
- **GPU ou processamento intensivo**: infraestrutura remota distinta somente
  quando disponível, aprovada e com custo conhecido. Não inferir GPU a partir
  de bibliotecas instaladas; máquinas 2-vCPU/8-GB não equivalem a infraestrutura
  de inferência em produção.
- **Dados privados**: permanecer na infraestrutura remota privada previamente
  autorizada e com tratamento/retentiva documentados; nunca exportar áudios,
  credenciais ou payloads brutos para logs, repositórios ou celular.

O dispositivo A15 **não deve participar como nó de computação** de fallback.
Se o ambiente remoto não suportar a tarefa, **abster-se e reportar o bloqueio**.
Nunca contornar essa falta usando CPU, RAM ou armazenamento do telefone.

## 3. Boundary antes de cada comando

1. Confirmar se o prompt é **Termux/A15** ou um ambiente Linux remoto.
2. Se o comando instala, processa, codifica, gera, treina ou salva dados de
   trabalho, executá-lo **somente remotamente**; abortar no A15.
3. Para BR-no-GTA V23, exigir branch autorizada, `git status` limpo quando
   aplicável, e as verificações de identidade previstas no bootstrap.
4. Não dar `git reset --hard`, `force-push`, não substituir checkout e não
   descartar WIP nem checkpoints; preservar a árvore e os recibos remotos.
5. Sem autorização explícita para gasto, permanecer dentro da franquia
   gratuita; verificar a cota real antes de jobs longos, sem provisionar
   recursos pagos ou aumentar máquina.
6. Informar separadamente: **CI passou**, **carga real executou**, **identidade
   vocal aprovada por humano**, **entrega/publicação**. Um resultado não
   substitui outro.

## 4. Tratamento de erros e incidentes

Se uma orientação mandar executar trabalho pesado no A15, interromper antes da
execução e substituir pelo comando equivalente para o runtime remoto. Se uma
sessão SSH fechar, verificar `gh codespace list` e reconectar; não reinstalar
nem reconfigurar automaticamente o A15. Se um Codespace parar, não considerá-lo
deletado sem evidência. Executar `gh codespace stop` do Termux **após** sair
do SSH, não na própria sessão remota.

## 5. Referências existentes

- `AGENTS.md` — hierarquia de autoridade do Harness, mantida integralmente;
- `docs/operations/br-v23-codespace-free-quota.md` — workstation V23, identidade
  e limites de recursos/custo;
- `scripts/workstations/br_v23_codespace_bootstrap.py` — gate real que recusa
  executar no A15.

**Regra operacional resumida:**
> **A15 = comando e controle. Computação, instalação, artefatos e dados de
> trabalho = infraestrutura remota autorizada. Sem fallback no telefone.**
