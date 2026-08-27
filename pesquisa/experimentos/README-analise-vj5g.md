# Motor de análise VJ5G

`analise_vj5g.py` executa a etapa **offline** da Fase 1:

1. valida o `window_log` combinado;
2. calcula a fronteira de Pareto vazão × Jain em cada janela comparável;
3. normaliza as métricas e calcula o produto de Barganha de Nash;
4. registra todos os vencedores em caso de empate;
5. ranqueia os schedulers por aparições na fronteira e vitórias de Nash.

## Entrada mínima

O CSV precisa conter:

```text
scheduler,window_id,aggregate_thr_mbps,jain_throughput
```

Quando disponíveis, `traffic_profile`, `num_ues`, `seed` e `bandwidth_mhz`
também identificam cada janela comparável. Os schedulers só são comparados
dentro da mesma combinação desses campos.

Por segurança metodológica, todas as colunas indicadas em `--group-by` devem
existir. Cada grupo precisa conter exatamente uma linha de cada scheduler, o
mesmo conjunto de schedulers e, quando `time_s` existir, o mesmo instante. O
programa rejeita duplicatas, janelas incompletas e entradas com apenas um
scheduler, em vez de produzir vitórias artificiais.

## Execução

```bash
python3 pesquisa/experimentos/analise_vj5g.py \
  --input pesquisa/resultados/pilar1_2_prototipo/window_log_combinado.csv \
  --output pesquisa/resultados/validacao_fase1
```

Saídas:

- `window_log_com_pareto.csv`: dados originais, Pareto, normalização e score;
- `vencedores_nash_por_janela.csv`: vencedor(es) por janela;
- `ranking_escalonadores.csv`: frequência na fronteira e vitórias de Nash;
- `metadata_analise.json`: parâmetros e referências da análise.

Por padrão, a referência de throughput é o máximo global do arquivo. Isso é
adequado para comparação experimental **offline**, mas usa o conjunto completo
e não é causal. Para uma referência de calibração fixa, informe:

```bash
--throughput-reference 100.0
```

A referência informada deve ser finita e pelo menos igual ao maior throughput
observado; isso evita que o clipping crie empates artificiais. `--epsilon`
também deve ser finito e não negativo.

## Testes

Não é necessário instalar `pytest`:

```bash
python3 -m unittest discover \
  -s pesquisa/experimentos/tests \
  -p 'test_*.py' \
  -v
```

Os testes cobrem dominância, trade-offs, duplicatas, validação, Nash, empates e
geração dos artefatos.
