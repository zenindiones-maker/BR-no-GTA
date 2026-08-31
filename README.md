# BR no GTA

Projeto **BR no GTA** — infraestrutura para automação, pesquisa, produção e publicação de conteúdo relacionado ao universo GTA.

## Objetivo

Construir uma plataforma modular capaz de organizar:

- pesquisa e coleta de informações;
- inteligência e análise de conteúdo;
- geração e organização de pautas;
- produção de vídeos e Shorts;
- integração com YouTube;
- armazenamento estruturado de dados;
- automação operacional;
- monitoramento e análise de resultados.

## Arquitetura

```text
BR/
├── brain/
│   ├── analytics/
│   ├── archive/
│   ├── ideas/
│   ├── knowledge/
│   ├── memory/
│   ├── radar/
│   └── scoring/
│
├── config/
│
├── content/
│   ├── research/
│   ├── scripts/
│   ├── shorts/
│   └── videos/
│
├── data/
│   ├── database/
│   ├── processed/
│   └── raw/
│
├── logs/
├── output/
│
└── YouTube/
    ├── credentials/
    ├── logs/
    ├── scripts/
    └── tokens/
