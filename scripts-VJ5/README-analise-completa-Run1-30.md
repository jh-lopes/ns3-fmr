# Análise completa — Bateria 3, runs 001–030

O script `analise_completa_Run1-30.py` audita e analisa as 30 primeiras runs
pareadas da Bateria 3. Ele não soma os quatro schedulers: RR, PF, MR e QoS são
políticas alternativas e são comparadas dentro do mesmo `rngRun`.

## Instalação

```bash
cd ~/ns3-fmr
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r scripts-VJ5/requirements-analise-Run1-30.txt
```

## Execução

```bash
python3 scripts-VJ5/analise_completa_Run1-30.py \
  --input pesquisa/resultados/3_bateria_test_3/executions.csv \
  --output pesquisa/resultados/3_bateria_test_3/Analise_Completa_Run1-30 \
  --first-run 1 \
  --last-run 30 \
  --bootstrap 1000
```

Por padrão, a auditoria é estrita: se alguma run não contiver exatamente RR,
PF, MR e QoS com o mesmo hash, a análise para depois de escrever
`01_Auditoria_Integridade/Auditoria_Run1-30.csv`. Use `--allow-incomplete`
somente para diagnóstico provisório; resultados incompletos não devem ser
apresentados como a análise definitiva.

## Organização

Cada tópico fica em subpasta própria:

```text
Analise_Completa_Run1-30/
├── 00_Tabelas_Dados/
├── 01_Auditoria_Integridade/
├── 02_Estatistica_Descritiva/
├── 03_Convergencia_IC95/
├── 04_Distribuicoes_ECDF/
├── 05_Comparacoes_Pareadas/
├── 06_Pareto_Nash/
├── 07_Desempenho_Distancia/
├── 08_PDR_Atraso_Cauda/
├── 09_Matriz_Vitorias_Regret/
├── 10_Jmin_Otimo/
├── 11_Analise_Temporal/
├── 12_Outliers_Diagnostico/
└── 13_Relatorio_Final/
```

Os gráficos são gravados em PNG de 300 DPI e PDF vetorial. As tabelas-fonte
ficam em CSV. `Relatorio_Resultados_Run1-30.md` contém o resumo automático e
`Metadata_Run1-30.json` registra premissas, runs, seed e parâmetros de Jmin.

## Jmin

O script calibra o limiar nas runs 1–15 e valida, sem reajuste, nas runs 16–30.
Ele relata:

- o joelho da curva throughput--justiça;
- o maior limiar com viabilidade de pelo menos 95% e perda de throughput de no
  máximo 5%;
- a distribuição bootstrap do limiar conservador;
- a tabela `Antes_Depois_Jmin_Run1-30.csv` na amostra de validação.

As janelas de 100 ms são usadas somente para diagnósticos temporais; a unidade
amostral inferencial continua sendo `rngRun`.
