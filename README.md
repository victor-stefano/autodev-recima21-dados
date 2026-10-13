# AutoDev: dados e scripts de análise do artigo RECIMA21

Material de reprodução do artigo **"AutoDev: orquestração autônoma e persistente para desenvolvimento de software"** (TCC de Engenharia da Computação, Universidade São Judas Tadeu, 2026).

O repositório contém apenas os **scripts de análise** e os **dados anonimizados** usados no artigo. O código-fonte do AutoDev não faz parte deste repositório; ele está disponível mediante solicitação aos autores. Página oficial da extensão: <https://autodev.stefanolabs.com>. Visual Studio Marketplace: `stefanolabs.autodev-vscode`.

## Conteúdo

```
corpus_multiprojeto/            Seções 2.4 e 3.4 do artigo
  dados/quota_anonimizado.jsonl   registro de cota do AutoDev, 26/08 a 27/09/2026 (1.079 registros)
  analise_autodev.py              script de análise (Python 3.9+, só biblioteca padrão)
  figura7.py                      gera a Figura 7 a partir de resultados/distribuicao_horaria.csv (requer matplotlib)
  resultados/                     saída do script (resumo.json e CSVs)
estudo_de_caso_ppt_maker/       Seção 3.5 do artigo
  analise.py                      script usado sobre as evidências do estudo de caso
  resultados/                     resultados agregados (ver observações abaixo)
```

## Como reproduzir o corpus multiprojeto

```
cd corpus_multiprojeto
python analise_autodev.py dados/quota_anonimizado.jsonl resultados
python figura7.py resultados/distribuicao_horaria.csv resultados/figura7.png   # opcional, requer matplotlib
```

O script recria a pasta `resultados/`, e todos os números do Quadro 4 e do Quadro 5 do artigo estão em `resultados/resumo.json`:

| No artigo | Em `resumo.json` |
|---|---|
| 27 execuções, 1.048 eventos, 777 chamadas, 213 commits, 142,5 h de operação | `filtro_execucoes.resultado` |
| Horas ativas (40,0 + 10,9 + 4,7 h) | `filtro_execucoes.resultado.horas_*` |
| 24 de 27 execuções iniciadas fora do horário; 90,4% da operação fora do horário | `complementares` |
| Decomposição das 142,5 h | `complementares.decomposicao_operacao_h` |
| 14 de 27 execuções atingiram o limite | `complementares.execucoes_que_atingiram_limite` |
| Episódios de cota: 31 de 35 (88,6%) e sensibilidade 20 de 24 | `episodios_cota.corrigida` e `episodios_cota.anterior` |
| Quadro 5 (por provedor) | `complementares.episodios_por_provedor` |
| Pico semanal de cota do Claude Code | `cota.claude_semanal_pico_pct` |
| Figura 7 e madrugada (0h–4h × 4h–8h) | `distribuicao_horaria.csv` e `complementares.madrugada_h` |

Todos os parâmetros (período, fuso, horário comercial, regra de execução, regra de episódios, limiar do watchdog) estão declarados no início de `analise_autodev.py`.

## Anonimização

No registro de cota, o campo `root` (caminho da pasta do projeto no computador do autor) foi reduzido ao nome da pasta do projeto, em minúsculas. Nenhum outro campo foi alterado, e os resultados obtidos com o registro original e com o anonimizado são idênticos. O arquivo foi recortado para o período analisado no artigo.

## Observações sobre o estudo de caso PPT_Maker

As evidências brutas do estudo de caso (transcrições das sessões, registro de eventos do AutoDev e histórico do Git) contêm material interno da empresa onde o projeto foi desenvolvido e **não são publicadas**. Por isso, `analise.py` está aqui para documentar o método, mas não pode ser executado sem essas evidências. Os resultados publicados são versões reduzidas da saída do script:

- `ppt_revisoes_qa.csv` e `ppt_intervencoes_do_usuario.csv` trazem só data, resultado e tipo, sem o texto das mensagens.
- `ppt_consumo_por_sessao.csv` traz só as sessões do projeto PPT_Maker.
- `ppt_tempo_por_fase.csv` traz as parcelas por fase arredondadas a uma casa; por isso, a soma da coluna `outro_parado_h` (9,8 h) difere do total calculado sem arredondamento em `resumo_ppt.json` (10,0 h).
- `ppt_falhas.csv` resume as seis falhas descritas no Quadro 7 do artigo. As falhas F4 e F6 foram caracterizadas pelos registros de energia do Windows (Kernel-Power 506 e 507).
- O custo equivalente pela API usa a tabela de preços de 25/09/2026 para o modelo Claude Opus 5.5 (US$ por milhão de tokens: entrada 4,00; saída 20,00; leitura de cache 0,20; escrita de cache 5,00 para 5 minutos e 8,00 para 1 hora) e a PTAX de 06/10/2026.

## Limitações dos dados

- O registro de eventos do AutoDev descarta o histórico acima de 10 MB; por isso, os desfechos das paradas de 26/08 a cerca de 15/09 foram reconstruídos apenas pelo registro de cota.
- Só o Claude Code informa a utilização da cota, e o percentual refere-se à conta inteira, inclusive o uso manual. Codex e Antigravity informam apenas o bloqueio.
- Só 248 das chamadas do Claude Code informaram tokens; a razão de tokens por commit é um limite inferior.
- A amostra é intencional, os projetos foram operados pelos próprios autores, e não há linha de base.

## Licenças

- Scripts (`*.py`): licença MIT (arquivo `LICENSE`).
- Dados e resultados (`*.jsonl`, `*.csv`, `*.json`): Creative Commons Atribuição 4.0 Internacional (arquivo `LICENSE-DADOS.md`).

## Como citar

Ver `CITATION.cff`. Após a publicação da versão no Zenodo, citar pelo DOI da versão.
