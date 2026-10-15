"""Figura 7 do artigo: commits e horas de operação por hora do dia (27 execuções).

Uso: python figura7.py resultados/distribuicao_horaria.csv figura7.png
Requer matplotlib (único script do repositório que não usa só a biblioteca padrão).
Dois painéis com o mesmo eixo horizontal: (a) quantidade de commits por hora;
(b) horas de operação por hora, divididas em agente ativo, espera após limite e outros.
"""
import csv
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

TINTA, TINTA2, MUDO, GRADE, FAIXA = "#0b0b0b", "#52514e", "#898781", "#e4e3df", "#f1f0ec"
COMMITS = "#52514e"                                   # série única: neutra
ATIVO, ESPERA, OUTROS = "#2a78d6", "#eb6834", "#1baf7a"  # paleta categórica validada, 1-3


def br(v, casas=1):
    return f"{v:.{casas}f}".replace(".", ",")


def faixa(ax, ytop, rotulo=True):
    ax.axvspan(7.5, 17.5, color=FAIXA, zorder=0, lw=0)
    if rotulo:
        ax.text(12.5, ytop, "8h–18h (horário comercial nos dias úteis)", ha="center",
                va="top", fontsize=6.5, color=TINTA2)


def chave(ax, x0, x1, y, texto):
    ax.annotate("", xy=(x0 - 0.4, y), xytext=(x1 + 0.4, y),
                arrowprops=dict(arrowstyle="-", color=MUDO, lw=0.8))
    ax.text((x0 + x1) / 2, y, texto, ha="center", va="bottom", fontsize=6.5, color=TINTA)


def main(arq, saida):
    L = list(csv.DictReader(open(arq, encoding="utf-8"), delimiter=";"))
    h = [int(r["hora_local"]) for r in L]
    com = [int(r["commits"]) for r in L]
    op = [float(r["horas_operacao"]) for r in L]
    at = [float(r["horas_agente_ativo"]) for r in L]
    es = [float(r["horas_parada_apos_limite"]) for r in L]
    ou = [max(o - a - e, 0) for o, a, e in zip(op, at, es)]

    def soma(v, a, b):
        return sum(v[i] for i in range(a, b))

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.3, 3.9), dpi=300, sharex=True,
                                 gridspec_kw={"height_ratios": [1, 1], "hspace": 0.32})
    fig.patch.set_facecolor("white")

    # (a) commits
    faixa(a1, 40.5)
    a1.bar(h, com, width=0.72, color=COMMITS, zorder=2)
    for x, v in zip(h, com):
        a1.text(x, v + 0.6, str(v), ha="center", va="bottom", fontsize=6.5, color=TINTA)
    chave(a1, 0, 3, 31.5, f"0h–4h: {soma(com, 0, 4)} commits")
    chave(a1, 4, 7, 13.0, f"4h–8h: {soma(com, 4, 8)} commits")
    a1.set_ylim(0, 42)
    a1.set_ylabel("Commits (quantidade)", color=TINTA2)
    a1.set_title(f"(a) Commits por hora do dia (total: {sum(com)})", loc="left",
                 fontsize=7.5, color=TINTA, fontweight="bold")

    # (b) horas de operação, empilhadas
    faixa(a2, 14.8)
    kw = dict(width=0.72, edgecolor="white", linewidth=0.6, zorder=2)
    a2.bar(h, at, color=ATIVO, label="Agente ativo", **kw)
    a2.bar(h, es, bottom=at, color=ESPERA, label="Espera após limite de cota", **kw)
    a2.bar(h, ou, bottom=[a + e for a, e in zip(at, es)], color=OUTROS,
           label="Outros intervalos", **kw)
    for x, v in zip(h, op):
        a2.text(x, v + 0.2, br(v), ha="center", va="bottom", fontsize=5.6, color=TINTA)
    a2.set_ylim(0, 15)
    a2.set_yticks(range(0, 15, 2))
    a2.set_ylabel("Horas de operação (h)", color=TINTA2)
    a2.set_title(f"(b) Horas de operação por hora do dia (total: {br(sum(op))} h)",
                 loc="left", fontsize=7.5, color=TINTA, fontweight="bold")
    a2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.24), ncol=3, frameon=False,
              fontsize=6.5, labelcolor=TINTA, handlelength=1.2, columnspacing=1.2)

    a2.set_xlim(-0.6, 23.6)
    a2.set_xticks(range(24))
    a2.set_xticklabels([f"{x}h" for x in range(24)], fontsize=6.3)
    a2.set_xlabel("Hora do dia (horário de Brasília)", color=TINTA2)
    for ax in (a1, a2):
        ax.grid(axis="y", color=GRADE, lw=0.6, zorder=1)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color(GRADE)
        ax.tick_params(colors=TINTA2, length=0)
    a1.tick_params(labelbottom=True)
    a1.set_xticks(range(24))
    a1.set_xticklabels([f"{x}h" for x in range(24)], fontsize=6.3)

    fig.savefig(saida, dpi=300, facecolor="white", bbox_inches="tight", pad_inches=0.04)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "figura7.png")
