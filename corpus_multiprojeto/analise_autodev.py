"""Análise reproduzível do registro de cota do AutoDev (artigo RECIMA21).

Uso:
    python analise_autodev.py quota.jsonl [pasta_saida]

Requer apenas Python 3.9+ (biblioteca padrão). Gera, na pasta de saída
(padrão: ./resultados):
    resumo.json                 todos os indicadores
    visao_geral.csv             indicadores do período, sem filtro de sessões
    projetos_commits.csv        commits por projeto, dentro/fora do horário comercial
    execucoes.csv               execuções (sessões) com a marca do filtro do artigo
    filtro_vs_artigo.csv        números do filtro comparados aos da versão anterior do artigo
    episodios_cota.csv          episódios de cota esgotada e desfecho (regra adotada)
    episodios_cota_regra_*.csv  os mesmos episódios pela outra regra, para comparação
    cota_semanal_claude.csv     pico semanal de uso de cota (seven_day) do Claude
    distribuicao_horaria.csv    commits e horas por hora do dia (base da Figura 7)

Formato de entrada (uma linha JSON por registro):
    call  : ts, provider, root, ms, ok, model, usd, tokens, quota[], usage{}
    limit : ts, provider, root, retryAt, source, kind
    work  : ts, provider, root, commit, mode, taskId
"""
import collections
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Parâmetros (todos declarados aqui para conferência)
# --------------------------------------------------------------------------
PERIODO_INICIO = "2026-08-26"      # data UTC do registro (inclusive)
PERIODO_FIM = "2026-09-27"         # data UTC do registro (inclusive)
FUSO_LOCAL = timezone(timedelta(hours=-3))   # Brasília, sem horário de verão
HORARIO_COMERCIAL = (8, 18)        # seg a sex, 8h <= hora < 18h (local)

# Execução: sequência de eventos do mesmo projeto em que o intervalo entre dois
# eventos consecutivos não passa de GAP_EXECUCAO. Uma execução é excluída se durar
# menos de FILTRO_MIN_DURACAO ou tiver menos de FILTRO_MIN_CHAMADAS chamadas.
# Regra adotada em 12/10/2026 no lugar da versão anterior do artigo, que não era
# reproduzível a partir do registro (ver filtro_vs_artigo.csv).
GAP_EXECUCAO = timedelta(hours=6)
FILTRO_MIN_DURACAO = timedelta(minutes=15)   # exclui execução com duração menor...
FILTRO_MIN_CHAMADAS = 5                       # ...ou com menos chamadas

# Episódios de cota esgotada
DUPLICATA = timedelta(minutes=2)       # mesmo projeto+provedor dentro de 2 min
FOLGA_RETRY = timedelta(hours=1)       # tolerância após retryAt
RETRY_PADRAO = timedelta(hours=5)      # quando o registro não traz retryAt
RETRY_TETO = timedelta(hours=6)        # teto da espera considerada
TROCA_MAX = timedelta(hours=1)         # outro provedor em menos de 1 h = troca
# Regra de agrupamento dos episódios:
#   "corrigida": o episódio termina na primeira chamada bem-sucedida do projeto;
#                um limite posterior abre outro episódio (confere com o events.jsonl).
#   "anterior" : limites do mesmo projeto+provedor antes de retryAt+1h formam um
#                episódio só (regra da análise prévia; junta paradas já resolvidas).
REGRA_EPISODIO = "corrigida"

# Chamada que falhou após pelo menos este tempo: derrubada pelo watchdog do AutoDev
# (chamada muda por 30 min). 17 das 21 têm 30 min; as outras, de 33 a 40 min.
WATCHDOG_MIN = timedelta(minutes=29.5)

# Números da versão anterior do artigo, só para registrar a diferença
ARTIGO = {"execucoes": 27, "eventos": 1039, "chamadas": 746, "commits": 207,
          "limites": 55, "horas_ativas": 52.1, "horas_operacao": 138}


def T(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def projeto(root):
    return root.replace("/", "\\").rstrip("\\").split("\\")[-1].lower()


def fora_do_horario(ts):
    t = T(ts).astimezone(FUSO_LOCAL)
    return t.weekday() >= 5 or not (HORARIO_COMERCIAL[0] <= t.hour < HORARIO_COMERCIAL[1])


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def horas(ms):
    return ms / 3.6e6


def gravar_csv(caminho, cab, linhas):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(cab)
        w.writerows(linhas)


def contar(evs):
    c = [r for r in evs if r["type"] == "call"]
    wd = WATCHDOG_MIN.total_seconds() * 1000
    ok = [r for r in c if r["ok"]]
    longas = [r for r in c if not r["ok"] and (r["ms"] or 0) >= wd]
    curtas = [r for r in c if not r["ok"] and (r["ms"] or 0) < wd]
    soma = lambda L: round(horas(sum(r["ms"] or 0 for r in L)), 1)
    return {
        "eventos": len(evs),
        "chamadas": len(c),
        "chamadas_ok": len(ok),
        "commits": sum(1 for r in evs if r["type"] == "work"),
        "limites": sum(1 for r in evs if r["type"] == "limit"),
        "horas_ativas": soma(c),
        "horas_chamadas_ok": soma(ok),
        "horas_falhas_watchdog": soma(longas),
        "n_falhas_watchdog": len(longas),
        "horas_outras_falhas": soma(curtas),
        "n_outras_falhas": len(curtas),
    }


def _fim_espera(l):
    t = T(l["ts"])
    ra = T(l["retryAt"]) if l.get("retryAt") else t + RETRY_PADRAO
    return min(ra, t + RETRY_TETO)


def agrupar_episodios(ded, calls, regra):
    eps, aberto = [], {}
    for l in ded:
        t = T(l["ts"])
        if regra == "corrigida":
            e = aberto.get(l["proj"])
            junta = e is not None and e["provider"] == l["provider"] and not any(
                c["proj"] == l["proj"] and c["ok"] and e["ultimo"] < T(c["ts"]) < t for c in calls)
        else:
            e = next((e for e in eps if e["proj"] == l["proj"] and e["provider"] == l["provider"]
                      and not e["fechado"] and t <= e["fim"] + FOLGA_RETRY), None)
            junta = e is not None
        if junta:
            e["n"] += 1
            e["ultimo"] = t
            e["fim"] = max(e["fim"], _fim_espera(l))
            continue
        if regra == "anterior":
            for x in eps:
                if x["proj"] == l["proj"]:
                    x["fechado"] = True
        e = dict(proj=l["proj"], provider=l["provider"], primeiro=t, ultimo=t,
                 fim=_fim_espera(l), n=1, fechado=False)
        eps.append(e)
        aberto[l["proj"]] = e
    return eps


def classificar_episodios(eps, calls):
    """Desfecho pela próxima chamada bem-sucedida do mesmo projeto após o último limite."""
    desf = collections.Counter()
    espera_h = 0.0
    linhas = []
    for e in eps:
        nxt = next((c for c in calls if c["proj"] == e["proj"] and c["ok"]
                    and T(c["ts"]) >= e["ultimo"]), None)
        if nxt is None:
            out, retomada = "sem retomada", ""
        else:
            tn = T(nxt["ts"])
            retomada = nxt["ts"]
            if nxt["provider"] != e["provider"] and tn - e["ultimo"] < TROCA_MAX:
                out = "troca de provedor"
            elif tn <= e["fim"] + FOLGA_RETRY:
                out = "espera programada"
                espera_h += (tn - e["primeiro"]).total_seconds() / 3600
            else:
                out = "retomada manual ou tardia"
        desf[out] += 1
        linhas.append([e["primeiro"].isoformat(), e["proj"], e["provider"], e["n"], out, retomada])
    auto = desf["troca de provedor"] + desf["espera programada"]
    lo, hi = wilson(auto, len(eps))
    return ({"episodios": len(eps), "desfechos": dict(desf), "autonomos": auto,
             "pct_autonomia": round(100 * auto / len(eps), 1),
             "ic95_wilson": [round(100 * lo, 1), round(100 * hi, 1)],
             "horas_espera_programada": round(espera_h, 1)}, linhas)


def main(arq, saida):
    os.makedirs(saida, exist_ok=True)
    todos = [json.loads(l) for l in open(arq, encoding="utf-8") if l.strip()]
    P = sorted((r for r in todos if PERIODO_INICIO <= r["ts"][:10] <= PERIODO_FIM),
               key=lambda r: r["ts"])
    for r in P:
        r["proj"] = projeto(r["root"])
    calls = [r for r in P if r["type"] == "call"]
    works = [r for r in P if r["type"] == "work"]
    lims = [r for r in P if r["type"] == "limit"]
    res = {"arquivo": os.path.basename(arq), "registros_no_arquivo": len(todos),
           "periodo_utc": [PERIODO_INICIO, PERIODO_FIM]}

    # ---------------- 1. Visão geral (sem filtro de sessões) ----------------
    vg = contar(P)
    vg["pct_chamadas_ok"] = round(100 * vg["chamadas_ok"] / vg["chamadas"], 1)
    vg["limites_por_provedor"] = dict(collections.Counter(r["provider"] for r in lims))
    res["visao_geral"] = vg
    gravar_csv(os.path.join(saida, "visao_geral.csv"), ["indicador", "valor"],
               [[k, v if not isinstance(v, dict) else json.dumps(v)] for k, v in vg.items()])

    # ---------------- 2. Commits por projeto ----------------
    pc = collections.OrderedDict()
    for r in works:
        d = pc.setdefault(r["proj"], [0, 0])
        d[1] += 1
        d[0] += fora_do_horario(r["ts"])
    tot_fora = sum(v[0] for v in pc.values())
    res["projetos_commits"] = {k: {"fora_do_horario": v[0], "total": v[1]} for k, v in pc.items()}
    res["commits_fora_do_horario"] = {"n": tot_fora, "total": len(works),
                                      "pct": round(100 * tot_fora / len(works), 1)}
    gravar_csv(os.path.join(saida, "projetos_commits.csv"),
               ["projeto", "fora_do_horario", "total"],
               [[k, v[0], v[1]] for k, v in pc.items()] + [["TOTAL", tot_fora, len(works)]])

    # ---------------- 3. Execuções e filtro do artigo ----------------
    por_proj = collections.defaultdict(list)
    for r in P:
        por_proj[r["proj"]].append(r)
    execs = []
    for proj, evs in por_proj.items():
        cur = [evs[0]]
        for a, b in zip(evs, evs[1:]):
            if T(b["ts"]) - T(a["ts"]) > GAP_EXECUCAO:
                execs.append(cur)
                cur = []
            cur.append(b)
        execs.append(cur)
    execs.sort(key=lambda s: s[0]["ts"])
    linhas, mantidas = [], []
    for i, s in enumerate(execs, 1):
        dur = T(s[-1]["ts"]) - T(s[0]["ts"])
        c = contar(s)
        mant = not (dur < FILTRO_MIN_DURACAO or c["chamadas"] < FILTRO_MIN_CHAMADAS)
        if mant:
            mantidas.append(s)
        linhas.append([i, s[0]["proj"], s[0]["ts"], s[-1]["ts"], round(dur.total_seconds() / 3600, 2),
                       c["eventos"], c["chamadas"], c["commits"], c["limites"], c["horas_ativas"],
                       "sim" if mant else "não"])
    gravar_csv(os.path.join(saida, "execucoes.csv"),
               ["id", "projeto", "inicio_utc", "fim_utc", "duracao_h", "eventos", "chamadas",
                "commits", "limites", "horas_ativas", "mantida_no_filtro"], linhas)
    filt = contar([r for s in mantidas for r in s])
    filt["execucoes"] = len(mantidas)
    cm = [r for s in mantidas for r in s if r["type"] == "work"]
    filt["commits_fora_do_horario"] = sum(fora_do_horario(r["ts"]) for r in cm)
    filt["pct_commits_fora_do_horario"] = round(100 * filt["commits_fora_do_horario"] / len(cm), 1)
    filt["horas_operacao"] = round(sum((T(s[-1]["ts"]) - T(s[0]["ts"])).total_seconds()
                                       for s in mantidas) / 3600, 1)
    res["filtro_execucoes"] = {"parametros": {"gap_h": GAP_EXECUCAO.total_seconds() / 3600,
                                              "min_duracao_min": FILTRO_MIN_DURACAO.total_seconds() / 60,
                                              "min_chamadas": FILTRO_MIN_CHAMADAS},
                               "execucoes_total": len(execs), "resultado": filt, "versao_anterior_do_artigo": ARTIGO,
                               "reproduz_versao_anterior": all(filt.get(k) == v for k, v in ARTIGO.items()
                                                      if k in ("execucoes", "eventos", "commits"))}
    gravar_csv(os.path.join(saida, "filtro_vs_artigo.csv"),
               ["indicador", "script", "versao_anterior_do_artigo", "diferenca"],
               [[k, filt.get(k), v, round(filt.get(k, 0) - v, 1)] for k, v in ARTIGO.items()])

    # ---------------- 4. Episódios de cota esgotada ----------------
    # (período inteiro, sem o filtro de execuções)
    ded = []
    for l in lims:
        if ded and ded[-1]["proj"] == l["proj"] and ded[-1]["provider"] == l["provider"] \
                and T(l["ts"]) - T(ded[-1]["ts"]) < DUPLICATA:
            continue
        ded.append(l)
    res["episodios_cota"] = {"limites_brutos": len(lims), "limites_sem_duplicata": len(ded),
                             "regra_adotada": REGRA_EPISODIO}
    for regra in ("corrigida", "anterior"):
        eps = agrupar_episodios(ded, calls, regra)
        r_ep, lin_ep = classificar_episodios(eps, calls)
        res["episodios_cota"][regra] = r_ep
        nome = "episodios_cota.csv" if regra == REGRA_EPISODIO else f"episodios_cota_regra_{regra}.csv"
        gravar_csv(os.path.join(saida, nome),
                   ["inicio_utc", "projeto", "provedor", "registros_limite", "desfecho", "retomada_utc"], lin_ep)

    # ---------------- 5. Cota convertida ----------------
    semanal = collections.defaultdict(float)
    leituras_5h = []
    for c in calls:
        for q in c.get("quota") or []:
            if q.get("kind") == "seven_day":
                k = q["resetsAt"][:10]
                semanal[k] = max(semanal[k], q["utilization"])
            elif q.get("kind") == "five_hour":
                leituras_5h.append(q["utilization"])
    gravar_csv(os.path.join(saida, "cota_semanal_claude.csv"), ["renovacao_utc", "pico_pct"],
               [[k, round(100 * v)] for k, v in sorted(semanal.items())])
    cl = [c for c in calls if c["provider"] == "claude"]
    com_tok = [c for c in cl if c.get("tokens")]
    tok = sum(c["tokens"] for c in com_tok)
    commits_claude = sum(1 for w in works if w["provider"] == "claude")
    res["cota"] = {
        "claude_semanal_pico_pct": {k: round(100 * v) for k, v in sorted(semanal.items())},
        "claude_janela_5h": {"leituras": len(leituras_5h),
                             "min_pct": round(100 * min(leituras_5h)) if leituras_5h else None,
                             "obs": "o CLI só informava a janela perto do limite; medida viesada"},
        "claude_tokens": {"chamadas_claude": len(cl), "chamadas_com_tokens": len(com_tok),
                          "tokens_milhoes": round(tok / 1e6, 1), "commits_claude": commits_claude,
                          "tokens_por_commit_milhoes_limite_inferior":
                              round(tok / 1e6 / commits_claude, 2) if commits_claude else None},
        "obs": "percentual de cota é da conta inteira, inclusive uso manual; Codex e Antigravity não informam cota",
    }

    # ---------------- 6. Indicadores complementares (execuções mantidas) ----------------
    fc = [r for s in mantidas for r in s]
    fcalls = [r for r in fc if r["type"] == "call"]
    seg = lambda c: (T(c["ts"]), T(c["ts"]) + timedelta(milliseconds=c["ms"] or 0))
    op_fora = sum(segundos_fora(T(s[0]["ts"]), T(s[-1]["ts"])) for s in mantidas) / 3600
    at = sum(horas(c["ms"] or 0) for c in fcalls)
    at_fora = sum(segundos_fora(*seg(c)) for c in fcalls) / 3600
    com_lim = [s for s in mantidas if any(r["type"] == "limit" for r in s)]
    dur = lambda s: (T(s[-1]["ts"]) - T(s[0]["ts"])).total_seconds() / 3600
    ativo_h, espera_h = collections.Counter(), collections.Counter()
    decomp = decompor_operacao(mantidas, ativo_h, espera_h)
    por_prov = collections.defaultdict(lambda: collections.Counter())
    for r in fc:
        p = por_prov[r["provider"]]
        if r["type"] == "call":
            p["chamadas"] += 1
            p["chamadas_ok"] += bool(r["ok"])
            p["ms"] += r["ms"] or 0
        elif r["type"] == "limit":
            p["limites"] += 1
        else:
            p["commits"] += 1
    fcl = [c for c in fcalls if c["provider"] == "claude"]
    ftok = [c for c in fcl if c.get("tokens")]
    ep_lin = list(csv.reader(open(os.path.join(saida, "episodios_cota.csv"), encoding="utf-8"), delimiter=";"))[1:]
    ep_prov = collections.defaultdict(collections.Counter)
    for l in ep_lin:
        ep_prov[l[2]][l[4]] += 1
    res["complementares"] = {
        "execucoes_iniciadas_fora_do_horario": sum(fora_do_horario(s[0]["ts"]) for s in mantidas),
        "horas_operacao_fora_do_horario": round(op_fora, 1),
        "pct_operacao_fora_do_horario": round(100 * op_fora / filt["horas_operacao"], 1),
        "horas_ativas_fora_do_horario": round(at_fora, 1),
        "pct_ativas_fora_do_horario": round(100 * at_fora / at, 1),
        "execucoes_que_atingiram_limite": len(com_lim),
        "horas_operacao_nessas_execucoes": round(sum(dur(s) for s in com_lim), 1),
        "projetos_nas_execucoes": sorted({s[0]["proj"] for s in mantidas}),
        "decomposicao_operacao_h": decomp,
        "por_provedor": {k: {"chamadas": v["chamadas"], "chamadas_ok": v["chamadas_ok"],
                             "horas_ativas": round(horas(v["ms"]), 1), "limites": v["limites"],
                             "commits": v["commits"]} for k, v in por_prov.items()},
        "claude_tokens_nas_execucoes": {"chamadas_claude": len(fcl), "chamadas_com_tokens": len(ftok),
                                        "tokens_milhoes": round(sum(c["tokens"] for c in ftok) / 1e6, 1)},
        "episodios_por_provedor": {k: dict(v) for k, v in ep_prov.items()},
        "ic95_wilson_por_provedor": {
            k: {"autonomos": v["troca de provedor"] + v["espera programada"], "episodios": sum(v.values()),
                "ic95": [round(100 * x, 1) for x in wilson(v["troca de provedor"] + v["espera programada"],
                                                            sum(v.values()))]}
            for k, v in ep_prov.items()},
    }

    # ---------------- 7. Distribuição por hora do dia (Figura 7) ----------------
    cm_h = collections.Counter(T(r["ts"]).astimezone(FUSO_LOCAL).hour for r in cm)
    op_h = collections.Counter()
    for s in mantidas:
        t, fim = T(s[0]["ts"]), T(s[-1]["ts"])
        while t < fim:
            loc = t.astimezone(FUSO_LOCAL)
            nxt = min(fim, loc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            op_h[loc.hour] += (nxt - t).total_seconds() / 3600
            t = nxt
    tot_op = sum(op_h.values())
    gravar_csv(os.path.join(saida, "distribuicao_horaria.csv"),
               ["hora_local", "commits", "pct_commits", "horas_operacao", "pct_horas_operacao",
                "horas_agente_ativo", "horas_parada_apos_limite"],
               [[h, cm_h[h], round(100 * cm_h[h] / len(cm), 2), round(op_h[h], 2),
                 round(100 * op_h[h] / tot_op, 2), round(ativo_h[h], 2), round(espera_h[h], 2)]
                for h in range(24)])
    res["complementares"]["madrugada_h"] = {
        "0h_a_4h": {"agente_ativo": round(sum(ativo_h[h] for h in range(0, 4)), 1),
                    "parada_apos_limite": round(sum(espera_h[h] for h in range(0, 4)), 1),
                    "commits": sum(cm_h[h] for h in range(0, 4))},
        "4h_a_8h": {"agente_ativo": round(sum(ativo_h[h] for h in range(4, 8)), 1),
                    "parada_apos_limite": round(sum(espera_h[h] for h in range(4, 8)), 1),
                    "commits": sum(cm_h[h] for h in range(4, 8))}}

    with open(os.path.join(saida, "resumo.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return res


def segundos_fora(x, y):
    """Segundos fora do horário comercial entre x e y (datetimes com fuso), por fatias de hora local."""
    s, t = 0.0, x
    while t < y:
        loc = t.astimezone(FUSO_LOCAL)
        nxt = min(y, loc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        if loc.weekday() >= 5 or not (HORARIO_COMERCIAL[0] <= loc.hour < HORARIO_COMERCIAL[1]):
            s += (nxt - t).total_seconds()
        t = nxt
    return s


def _por_hora(cont, x, y):
    t = x
    while t < y:
        loc = t.astimezone(FUSO_LOCAL)
        nxt = min(y, loc.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        cont[loc.hour] += (nxt - t).total_seconds() / 3600
        t = nxt


def decompor_operacao(mantidas, ativo_h=None, espera_h=None):
    """Divide as horas de operação em: ao menos um agente ativo; parada após registro de
    limite (intervalo > 15 min iniciado até 2 min antes de um limite ou contendo um limite);
    outros intervalos (e, entre eles, os maiores que 15 min)."""
    ativo = apos_limite = outros = outros_longos = 0.0
    n_longos = 0
    for s in mantidas:
        ini, fim = T(s[0]["ts"]), T(s[-1]["ts"])
        cob = []
        for x, y in sorted((T(c["ts"]), T(c["ts"]) + timedelta(milliseconds=c["ms"] or 0))
                           for c in s if c["type"] == "call"):
            if cob and x <= cob[-1][1]:
                cob[-1][1] = max(cob[-1][1], y)
            else:
                cob.append([x, y])
        ativo += sum((min(y, fim) - x).total_seconds() for x, y in cob if x < fim) / 3600
        if ativo_h is not None:
            for x, y in cob:
                if x < fim:
                    _por_hora(ativo_h, x, min(y, fim))
        lim = [T(r["ts"]) for r in s if r["type"] == "limit"]
        pos = ini
        for x, y in cob + [[fim, fim]]:
            if x > pos:
                g = (x - pos).total_seconds() / 3600
                if g > 0.25 and any(pos - timedelta(minutes=2) <= l <= x for l in lim):
                    apos_limite += g
                    if espera_h is not None:
                        _por_hora(espera_h, pos, x)
                else:
                    outros += g
                    if g > 0.25:
                        outros_longos += g
                        n_longos += 1
            pos = max(pos, y)
    return {"agente_ativo": round(ativo, 1), "parada_apos_limite": round(apos_limite, 1),
            "outros_intervalos": round(outros, 1), "outros_maiores_que_15min": round(outros_longos, 1),
            "n_outros_maiores_que_15min": n_longos}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    r = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "resultados")
    print(json.dumps(r, ensure_ascii=False, indent=2))
