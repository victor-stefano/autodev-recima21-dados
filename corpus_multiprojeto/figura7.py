"""Figura 7 do artigo: commits e horas de operação por hora do dia.

Uso: python figura7.py resultados/distribuicao_horaria.csv figura7.png
Requer matplotlib (único script do repositório que não usa só a biblioteca padrão).
As duas séries estão em percentual do próprio total, para caberem num único eixo.
"""
import csv
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

AZUL, LARANJA = "#2a78d6", "#eb6834"          # paleta categórica validada, posições 1 e 2
TINTA, TINTA2, GRADE, FAIXA = "#0b0b0b", "#52514e", "#e4e3df", "#f1f0ec"


def main(arq, saida):
    linhas = list(csv.DictReader(open(arq, encoding="utf-8"), delimiter=";"))
    horas = [int(r["hora_local"]) for r in linhas]
    commits = [float(r["pct_commits"]) for r in linhas]
    operacao = [float(r["pct_horas_operacao"]) for r in linhas]
    n_commits = sum(int(r["commits"]) for r in linhas)
    h_op = sum(float(r["horas_operacao"]) for r in linhas)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig, ax = plt.subplots(figsize=(6.3, 3.2), dpi=300)
    fig.patch.set_facecolor("white")

    ax.axvspan(7.5, 17.5, color=FAIXA, zorder=0, lw=0)
    ax.text(12.5, 14.6, "8h–18h: horário comercial (dias úteis)", ha="center", va="top",
            fontsize=7.5, color=TINTA2)

    ax.bar(horas, commits, width=0.72, color=AZUL, zorder=2,
           label=f"Commits ({n_commits} = 100%)")
    ax.plot(horas, operacao, color=LARANJA, lw=2, marker="o", ms=3.5, zorder=3,
            label=f"Horas de operação ({h_op:.1f} h = 100%)".replace(".", ","))

    ax.set_xlim(-0.6, 23.6)
    ax.set_ylim(0, 15)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h}h" for h in range(0, 24, 2)])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlabel("Hora do dia (horário de Brasília)", color=TINTA2)
    ax.set_ylabel("% do total da série", color=TINTA2)
    ax.grid(axis="y", color=GRADE, lw=0.6, zorder=1)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(GRADE)
    ax.tick_params(colors=TINTA2, length=0)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=7.5,
              labelcolor=TINTA, borderaxespad=0.2, handlelength=1.6)

    fig.tight_layout()
    fig.savefig(saida, dpi=300, facecolor="white")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "figura7.png")
