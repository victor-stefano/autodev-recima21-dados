"""Análise do estudo de caso AutoDev / PPT_Maker.

Lê só as cópias em ../ (evidências) e grava os resultados em ./resultados/.
Rodar: py analise.py   (Python 3.11, só biblioteca padrão)
"""

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
EV = AQUI.parent
SAIDA = AQUI / "resultados"
SAIDA.mkdir(exist_ok=True)

# US$ por milhão de tokens. Fonte: documentação oficial da API (skill claude-api,
# tabela de 25/09/2026), copiada em ../06_precos_e_cambio/precos_api.txt.
# Leitura de cache = 0,1x a entrada, exceto Opus 5.5 (0,20) e Fable 5.1 (0,25).
# Escrita de cache = 1,25x a entrada (5 min) e 2x (1 h).
BASE = {
    "claude-fable-5-1": (10, 50), "claude-fable-5": (10, 50), "claude-opus-5-5": (4, 20),
    "claude-opus-5": (5, 25), "claude-opus-4-8": (5, 25), "claude-opus-4-7": (5, 25),
    "claude-opus-4-6": (5, 25), "claude-sonnet-5-5": (2, 10), "claude-sonnet-5": (2, 10),
    "claude-sonnet-4-6": (3, 15), "claude-haiku-4-5": (1, 5),
}
LEITURA = {"claude-opus-5-5": 0.20, "claude-fable-5-1": 0.25, "claude-sonnet-5-5": 0.20}
PTAX = 4.9698  # R$ por US$, venda, 06/10/2026 (Banco Central do Brasil, conferido)


def preco(modelo):
    for k, (i, o) in BASE.items():
        if modelo and modelo.startswith(k):
            return i, o, LEITURA.get(k, i * 0.1)
    return None


def jsonl(caminho):
    for linha in open(caminho, encoding="utf-8", errors="replace"):
        try:
            yield json.loads(linha)
        except json.JSONDecodeError:
            continue


def custo(u, p):
    pi, po, pr = p
    cc = u.get("cache_creation") or {}
    cw = u.get("cache_creation_input_tokens", 0)
    w1, w5 = cc.get("ephemeral_1h_input_tokens", 0), cc.get("ephemeral_5m_input_tokens", 0)
    if w1 + w5 != cw:
        w1, w5 = cw, 0
    i, o, r = u.get("input_tokens", 0), u.get("output_tokens", 0), u.get("cache_read_input_tokens", 0)
    com = (i * pi + o * po + r * pr + w5 * pi * 1.25 + w1 * pi * 2) / 1e6
    sem = ((i + r + cw) * pi + o * po) / 1e6
    return com, sem, i + o + r + cw, o, r


def papel(primeiro_texto, entrypoint):
    if entrypoint not in ("sdk-cli", "sdk-ts", "sdk-py"):
        return "Uso direto"
    if primeiro_texto.startswith("A participant has declared the goal met"):
        return "Auditor"
    m = re.search(r"(1 Dev|2 Revisor QA|3 Manager)", primeiro_texto)
    return m.group(1) if m else "AutoDev (outro)"


def sessoes(pasta):
    """Uma linha por sessão: papel, respostas, tokens e custo."""
    linhas = []
    for f in sorted(pasta.glob("*.jsonl")):
        vistos, ep, primeiro, ini, fim = {}, None, None, None, None
        for d in jsonl(f):
            ep = ep or d.get("entrypoint")
            ts = d.get("timestamp")
            if ts:
                ini, fim = ini or ts, ts
            if primeiro is None and d.get("type") == "user":
                c = d["message"].get("content")
                primeiro = c if isinstance(c, str) else " ".join(
                    x.get("text", "") for x in c if isinstance(x, dict))
            m = d.get("message") or {}
            if d.get("type") == "assistant" and isinstance(m, dict) and m.get("usage") and m.get("id"):
                vistos[m["id"]] = (m.get("model"), m["usage"])  # última linha de cada mensagem
        soma = Counter()
        for modelo, u in vistos.values():
            p = preco(modelo)
            if not p:
                continue
            com, sem, tok, out, read = custo(u, p)
            soma.update(resp=1, tok=tok, out=out, read=read)
            soma["com"] += com
            soma["sem"] += sem
        if soma["resp"]:
            linhas.append({
                "projeto": pasta.name, "sessao": f.stem, "papel": papel(primeiro or "", ep),
                "inicio_utc": ini, "fim_utc": fim, "respostas": soma["resp"],
                "tokens": soma["tok"], "tokens_saida": soma["out"], "tokens_cache_lido": soma["read"],
                "custo_api_usd": round(soma["com"], 2), "custo_sem_cache_usd": round(soma["sem"], 2),
            })
    return linhas


def gravar_csv(nome, linhas):
    if not linhas:
        return
    with open(SAIDA / nome, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(linhas[0]), delimiter=";")
        w.writeheader()
        w.writerows(linhas)


def quando(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def tempo_por_fase(fases, esperas, resumo):
    """Divide o tempo de cada fase em agentes ativos, espera por limite, parada F4 e outro."""
    # Agentes ativos = intervalos com atividade nas transcrições do AutoDev no PPT,
    # emendando pausas de até 10 minutos.
    marcas = []
    for f in (EV / "02_transcricoes_claude_code" / "c--DEV-PPT").glob("*.jsonl"):
        ep = None
        for d in jsonl(f):
            ep = ep or d.get("entrypoint")
            if ep == "sdk-cli" and d.get("timestamp"):
                marcas.append(quando(d["timestamp"]))
    marcas.sort()
    ativos, a, b = [], marcas[0], marcas[0]
    for x in marcas[1:]:
        if (x - b).total_seconds() <= 600:
            b = x
        else:
            ativos.append((a, b))
            a = b = x
    ativos.append((a, b))

    limites = [(quando(e["inicio_utc"]), quando(e["retomada_utc"])) for e in esperas]
    # Falha F4: reinicialização do Windows durante a espera (entre 18:14 e 18:57 de 06/10,
    # horário de Brasília); a espera terminaria às 23:00 UTC, mas a execução não voltou
    # até a mensagem do usuário. Conta-se só o que passou do fim da espera.
    f4 = (quando("2026-10-06T23:00:00Z"), quando("2026-10-07T10:21:44Z"))
    # Falha F6: o computador entrou em suspensão durante uma chamada do Dev (Kernel-Power
    # 506 às 17:58:20 de 07/10 e 507 às 08:15:51 de 08/10, horário de Brasília). O relógio
    # do watchdog parou junto; ao acordar, o AutoDev derrubou a chamada muda e retomou sozinho.
    f6 = (quando("2026-10-07T20:58:20Z"), quando("2026-10-08T11:15:51Z"))
    # Fases pedidas depois pelo usuário contam a partir do pedido.
    pedidos = {10: quando("2026-10-08T15:35:47Z"), 11: quando("2026-10-08T23:18:49Z"),
               12: quando("2026-10-09T23:29:17Z")}

    def sobra(a, b, c, d):
        return max(0.0, (min(b, d) - max(a, c)).total_seconds() / 3600)

    fim = datetime.fromisoformat("2026-10-05T20:53:00-03:00")  # commit da fase 0 (b4bdf35)
    saida = []
    for f in fases:
        n, e = f["fase"], datetime.fromisoformat(f["ultimo_commit"])
        s = max(fim, pedidos.get(n, fim))
        total = (e - s).total_seconds() / 3600
        ativo = sum(sobra(s, e, a, b) for a, b in ativos)
        lim = sum(sobra(s, e, a, b) for a, b in limites)
        par = sobra(s, e, *f4)
        par6 = sobra(s, e, *f6)
        saida.append({"fase": n, "inicio": s.isoformat(), "fim": e.isoformat(), "total_h": round(total, 1),
                      "agentes_ativos_h": round(ativo, 1), "espera_limite_h": round(lim, 1),
                      "parada_falha_F4_h": round(par, 1), "suspensao_falha_F6_h": round(par6, 1),
                      "outro_parado_h": round(max(0.0, total - ativo - lim - par - par6), 1)})
        fim = e
    gravar_csv("ppt_tempo_por_fase.csv", saida)
    resumo["tempo_fases_h"] = {k: round(sum(x[k] for x in saida), 1) for k in (
        "total_h", "agentes_ativos_h", "espera_limite_h", "parada_falha_F4_h", "suspensao_falha_F6_h",
        "outro_parado_h")}


INICIO_EXEC = datetime.fromisoformat("2026-10-05T18:39:00-03:00")
FIM_EXEC = datetime.fromisoformat("2026-10-10T06:40:00-03:00")


def horario_comercial(d):
    """Segunda a sexta, das 8h às 18h, no horário de Brasília (mesma definição do corpus)."""
    return d.weekday() < 5 and 8 <= d.hour < 18


def commits_por_horario(arquivo, resumo):
    """Distribui todos os commits do Git feitos durante a execução entre dentro e fora do horário comercial.

    Aceita linhas 'hash|data' ou 'hash|data|autor|assunto' (data no formato git --date=iso).
    """
    linhas = []
    for linha in open(arquivo, encoding="utf-8-sig"):
        if not linha.strip():
            continue
        h, data = linha.rstrip("\n").split("|", 3)[:2]
        d = datetime.strptime(data.strip(), "%Y-%m-%d %H:%M:%S %z")
        if INICIO_EXEC <= d <= FIM_EXEC:
            linhas.append({"commit": h, "data_local": d.isoformat(),
                           "horario_comercial": "sim" if horario_comercial(d) else "não"})
    linhas.sort(key=lambda x: x["data_local"])
    gravar_csv("ppt_commits_horario.csv", linhas)
    minutos, fora = 0, 0
    t = INICIO_EXEC
    while t < FIM_EXEC:
        minutos += 1
        fora += not horario_comercial(t)
        t += timedelta(minutes=1)
    n = len(linhas)
    n_hc = sum(1 for x in linhas if x["horario_comercial"] == "sim")
    resumo["commits_por_horario"] = {
        "commits_na_execucao": n, "em_horario_comercial": n_hc, "fora_do_horario": n - n_hc,
        "pct_commits_fora": round(100 * (n - n_hc) / n, 1),
        "pct_tempo_fora": round(100 * fora / minutos, 1),
    }


def main():
    resumo = {}

    # 1. Consumo por sessão em todos os projetos de C:\DEV
    todas = []
    for pasta in sorted((EV / "02_transcricoes_claude_code").iterdir()):
        todas += sessoes(pasta)
    gravar_csv("consumo_por_sessao.csv", todas)

    por_proj = defaultdict(Counter)
    for s in todas:
        grupo = "Uso direto" if s["papel"] == "Uso direto" else "AutoDev"
        por_proj[(s["projeto"], grupo)].update(
            respostas=s["respostas"], tokens=s["tokens"], tokens_saida=s["tokens_saida"],
            tokens_cache_lido=s["tokens_cache_lido"])
        por_proj[(s["projeto"], grupo)]["custo"] += s["custo_api_usd"]
        por_proj[(s["projeto"], grupo)]["sem"] += s["custo_sem_cache_usd"]
    gravar_csv("consumo_por_projeto.csv", [
        {"projeto": p, "grupo": g, "respostas": c["respostas"], "tokens": c["tokens"],
         "custo_api_usd": round(c["custo"], 2), "custo_sem_cache_usd": round(c["sem"], 2)}
        for (p, g), c in sorted(por_proj.items())])

    tot = defaultdict(Counter)
    for (p, g), c in por_proj.items():
        tot[g].update(c)
    resumo["total_por_grupo"] = {
        g: {"respostas": c["respostas"], "tokens": c["tokens"], "tokens_saida": c["tokens_saida"],
            "cache_lido_pct": round(c["tokens_cache_lido"] / c["tokens"] * 100, 1),
            "custo_api_usd": round(c["custo"], 2), "custo_sem_cache_usd": round(c["sem"], 2),
            "economia_cache_pct": round((1 - c["custo"] / c["sem"]) * 100, 1),
            "custo_api_brl": round(c["custo"] * PTAX, 2)}
        for g, c in tot.items()}

    # 2. Custo por papel no PPT
    ppt = [s for s in todas if s["projeto"].lower() == "c--dev-ppt"]
    por_papel = defaultdict(Counter)
    for s in ppt:
        por_papel[s["papel"]].update(sessoes=1, respostas=s["respostas"], tokens=s["tokens"],
                                     tokens_saida=s["tokens_saida"])
        por_papel[s["papel"]]["custo"] += s["custo_api_usd"]
    # Uso manual paralelo da mesma conta, na mesma pasta, durante a execução
    auto = [s for s in ppt if s["papel"] != "Uso direto"]
    man = [s for s in ppt if s["papel"] == "Uso direto"]

    def _s(lista, k):
        return sum(x[k] for x in lista)
    resumo["ppt_uso_manual_paralelo"] = {
        "respostas": _s(man, "respostas"), "tokens": _s(man, "tokens"),
        "custo_api_usd": round(_s(man, "custo_api_usd"), 2),
        "pct_tokens_do_projeto": round(100 * _s(man, "tokens") / (_s(man, "tokens") + _s(auto, "tokens")), 1),
        "pct_custo_do_projeto": round(100 * _s(man, "custo_api_usd")
                                      / (_s(man, "custo_api_usd") + _s(auto, "custo_api_usd")), 1)}
    gravar_csv("ppt_custo_por_papel.csv", [
        {"papel": k, "sessoes": c["sessoes"], "respostas": c["respostas"], "tokens": c["tokens"],
         "tokens_saida": c["tokens_saida"], "custo_api_usd": round(c["custo"], 2)}
        for k, c in sorted(por_papel.items(), key=lambda kv: -kv[1]["custo"])])

    # 3. Eventos do AutoDev (execução arquivada + atual)
    # A execução atual foi restaurada a partir da arquivada em 05/10/2026, então os
    # eventos iniciais estão nos dois arquivos: um evento conta uma vez só.
    unicos = {}
    for nome in ("execucao_arquivada_2026-10-05", "execucao_atual"):
        for e in jsonl(EV / "01_autodev_registros" / nome / "events.jsonl"):
            unicos[(e.get("ts"), e.get("type"), e.get("role"), (e.get("message") or "")[:200])] = e
    eventos = sorted(unicos.values(), key=lambda e: e.get("ts", ""))

    interv = [{"data_utc": e["ts"], "mensagem": (e.get("message") or "")[:160].replace("\n", " ")}
              for e in eventos if e.get("type") == "chat.user"]
    gravar_csv("ppt_intervencoes_do_usuario.csv", interv)
    resumo["intervencoes_usuario"] = len(interv)

    tipos = Counter(e.get("type") for e in eventos)
    resumo["eventos"] = {k: tipos[k] for k in (
        "thread.turn", "agent.tool", "thread.post", "rate_limited", "gate.requested",
        "gate.auto_approved", "loop.completed", "thread.turn_failed", "agent.boundary")}

    # Esperas por limite de uso: do aviso até o horário de retomada
    esperas = []
    for e in eventos:
        if e.get("type") == "loop.waiting" and "until" in (e.get("message") or ""):
            ate = re.search(r"until (\S+Z)", e["message"]).group(1)
            esperas.append({"inicio_utc": e["ts"], "retomada_utc": ate,
                            "horas": round((quando(ate) - quando(e["ts"])).total_seconds() / 3600, 2)})
    gravar_csv("ppt_esperas_limite_de_uso.csv", esperas)
    resumo["esperas_limite"] = {"quantidade": len(esperas),
                                "horas_total": round(sum(x["horas"] for x in esperas), 1)}

    # Rodadas de revisão do Revisor QA (classificação por palavras; conferir à mão no CSV)
    rev = []
    for e in eventos:
        if e.get("type") == "thread.post" and e.get("role") == "2 Revisor QA":
            t = e.get("message") or ""
            devolveu = bool(re.search(
                r'(?i)ficam? \d+ "?alterar|faltam? \d+ "?alterar|só falta|devolv|alterar"? pendente: [1-9]|\| *alterar', t)) \
                and not re.search(r'(?i)sem "?alterar"? pendente|nenhum "?alterar|não há "?alterar'
                                  r'|aprovad[ao],? sem "?alterar', t)
            rev.append({"data_utc": e["ts"], "resultado": "devolveu com Alterar" if devolveu else "aprovou",
                        "inicio": t[:140].replace("\n", " ")})
    gravar_csv("ppt_revisoes_qa.csv", rev)
    resumo["revisoes_qa"] = Counter(r["resultado"] for r in rev)

    # 4. Fases pelo git
    fases = {}
    for linha in open(EV / "03_git" / "git_log.txt", encoding="utf-8"):
        h, data, autor, assunto = linha.rstrip("\n").split("|", 3)
        m = re.match(r"Fase (\d+)", assunto)
        if m:
            n = int(m.group(1))
            d = datetime.strptime(data.strip(), "%Y-%m-%d %H:%M:%S %z")
            a, b, k = fases.get(n, (d, d, 0))
            fases[n] = (min(a, d), max(b, d), k + 1)
    ordem = sorted(fases)
    linhas = []
    fim_anterior = None
    for n in ordem:
        a, b, k = fases[n]
        inicio = fim_anterior or a
        linhas.append({"fase": n, "commits": k, "primeiro_commit": a.isoformat(), "ultimo_commit": b.isoformat(),
                       "horas_desde_fase_anterior": round((b - inicio).total_seconds() / 3600, 1)})
        fim_anterior = b
    gravar_csv("ppt_fases_git.csv", linhas)

    tempo_por_fase(linhas, esperas, resumo)

    commits = sum(1 for _ in open(EV / "03_git" / "git_log.txt", encoding="utf-8"))
    resumo["git"] = {"commits": commits, "commits_de_fase": sum(f[2] for f in fases.values()),
                     "arquivos_versionados": sum(1 for _ in open(EV / "03_git" / "arquivos_versionados.txt",
                                                                 encoding="utf-8"))}
    commits_por_horario(EV / "03_git" / "git_log.txt", resumo)
    resumo["gerado_em_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (SAIDA / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2, default=dict),
                                        encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2, default=dict))


if __name__ == "__main__":
    main()
