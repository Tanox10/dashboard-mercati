"""
Script di raccolta dati e calcolo del sentiment finanziario.
Eseguito ogni giorno da GitHub Actions. Scrive docs/data.json,
che viene letto dal sito (docs/index.html) pubblicato con GitHub Pages.

Nessuna chiave API richiesta tranne FRED_API_KEY (gratuita, vedi README).
"""

import json
import os
import datetime
import feedparser
import yfinance as yf
import requests

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ---------------------------------------------------------------------
# 1. DATI DI MERCATO (yfinance, nessuna chiave richiesta)
#    Per ogni indice: prezzo, variazione 1 giorno / 1 mese / 1 anno
# ---------------------------------------------------------------------

MARKET_TICKERS = {
    "FTSE MIB (Italia)": "FTSEMIB.MI",
    "S&P 500 (USA)": "^GSPC",
    "Stoxx 600 (Eurozona)": "^STOXX",
    "MSCI World ETF": "URTH",
    "VIX (volatilitÃ  USA)": "^VIX",
}


def _pct_change(hist, giorni_indietro):
    """Variazione percentuale rispetto a circa N giorni di calendario fa."""
    if len(hist) < 2:
        return None
    target_date = hist.index[-1] - datetime.timedelta(days=giorni_indietro)
    prima = hist[hist.index <= target_date]
    if prima.empty:
        return None
    valore_prima = float(prima["Close"].iloc[-1])
    valore_ora = float(hist["Close"].iloc[-1])
    if valore_prima == 0:
        return None
    return round((valore_ora / valore_prima - 1) * 100, 2)


def get_market_data():
    result = {}
    for name, ticker in MARKET_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="13mo")
            if hist.empty:
                continue
            last_price = float(hist["Close"].iloc[-1])
            sma50 = float(hist["Close"].tail(50).mean())
            sma200 = float(hist["Close"].tail(200).mean())

            var_1g = _pct_change(hist, 1)
            var_1m = _pct_change(hist, 30)
            var_1a = _pct_change(hist, 365)

            trend = None
            if var_1a is not None:
                if var_1a <= -20:
                    trend = "bear market"
                elif var_1a <= -10:
                    trend = "correzione"
                elif var_1a >= 15:
                    trend = "trend positivo forte"
                else:
                    trend = "trend positivo"

            result[name] = {
                "prezzo": round(last_price, 2),
                "variazione_1g_pct": var_1g,
                "variazione_1m_pct": var_1m,
                "variazione_1a_pct": var_1a,
                "sopra_media_50gg": last_price > sma50,
                "sopra_media_200gg": last_price > sma200,
                "trend": trend,
            }
        except Exception as e:
            result[name] = {"errore": str(e)}
    return result


# ---------------------------------------------------------------------
# 2. DATI MACRO (FRED per USA, Eurostat per Eurozona/Italia - REST, no key)
#    Ogni indicatore mostra: valore attuale, valore di 12 mesi fa, delta
# ---------------------------------------------------------------------

def get_fred_yoy(series_id, is_index=False):
    if not FRED_API_KEY:
        return None
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
        "&sort_order=desc&limit=400"
    )
    try:
        r = requests.get(url, timeout=15)
        obs = [o for o in r.json()["observations"] if o["value"] != "."]
        if not obs:
            return None
        attuale = obs[0]
        data_attuale = datetime.datetime.strptime(attuale["date"], "%Y-%m-%d")
        target = data_attuale - datetime.timedelta(days=365)

        anno_fa = min(
            obs,
            key=lambda o: abs(
                (datetime.datetime.strptime(o["date"], "%Y-%m-%d") - target).days
            ),
        )

        valore_attuale = float(attuale["value"])
        valore_anno_fa = float(anno_fa["value"])

        out = {
            "data": attuale["date"],
            "valore": valore_attuale,
            "valore_anno_fa": valore_anno_fa,
            "variazione": round(valore_attuale - valore_anno_fa, 2),
        }

        if is_index and valore_anno_fa != 0:
            out["inflazione_annua_pct"] = round(
                (valore_attuale / valore_anno_fa - 1) * 100, 2
            )

        return out
    except Exception:
        return None


def get_eurostat_yoy(dataset, params, label):
    url = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}?format=JSON&lang=EN&{params}"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        time_index = data["dimension"]["time"]["category"]["index"]
        periodi_ordinati = sorted(time_index.items(), key=lambda x: x[1])
        valori = data["value"]

        serie = [
            (periodo, valori[str(pos)])
            for periodo, pos in periodi_ordinati
            if str(pos) in valori
        ]
        if len(serie) < 2:
            return None

        periodo_attuale, valore_attuale = serie[-1]

        indietro = 12 if len(periodo_attuale) > 6 else 4
        idx_anno_fa = max(0, len(serie) - 1 - indietro)
        periodo_anno_fa, valore_anno_fa = serie[idx_anno_fa]

        return {
            "nome": label,
            "periodo": periodo_attuale,
            "valore": round(float(valore_attuale), 2),
            "valore_anno_fa": round(float(valore_anno_fa), 2),
            "variazione": round(float(valore_attuale) - float(valore_anno_fa), 2),
        }
    except Exception:
        return None


def get_macro_data():
    macro = []

    spread = get_fred_yoy("T10Y2Y")
    if spread:
        macro.append({
            "nome": "Spread rendimenti USA 10Y-2Y",
            "unita": "punti %",
            **{k: v for k, v in spread.items() if k != "inflazione_annua_pct"},
        })

    cpi = get_fred_yoy("CPIAUCSL", is_index=True)
    if cpi and "inflazione_annua_pct" in cpi:
        macro.append({
            "nome": "Inflazione USA (CPI annuo)",
            "unita": "%",
            "valore": cpi["inflazione_annua_pct"],
            "valore_anno_fa": None,
            "variazione": None,
            "data": cpi["data"],
        })

    unrate = get_fred_yoy("UNRATE")
    if unrate:
        macro.append({
            "nome": "Disoccupazione USA",
            "unita": "%",
            **{k: v for k, v in unrate.items() if k != "inflazione_annua_pct"},
        })

    debito_usa = get_fred_yoy("GFDEGDQ188S")
    if debito_usa:
        macro.append({
            "nome": "Debito/PIL USA",
            "unita": "%",
            **{k: v for k, v in debito_usa.items() if k != "inflazione_annua_pct"},
        })

    infl_ea = get_eurostat_yoy(
        "prc_hicp_manr", "geo=EA&coicop=CP00", "Inflazione Eurozona (HICP)"
    )
    if infl_ea:
        infl_ea["unita"] = "%"
        macro.append(infl_ea)

    infl_it = get_eurostat_yoy(
        "prc_hicp_manr", "geo=IT&coicop=CP00", "Inflazione Italia (HICP)"
    )
    if infl_it:
        infl_it["unita"] = "%"
        macro.append(infl_it)

    disoccup_ea = get_eurostat_yoy(
        "une_rt_m", "geo=EA&s_adj=SA&age=TOTAL&sex=T&unit=PC_ACT",
        "Disoccupazione Eurozona"
    )
    if disoccup_ea:
        disoccup_ea["unita"] = "%"
        macro.append(disoccup_ea)

    return macro


# ---------------------------------------------------------------------
# 3. NEWS (RSS, nessuna chiave richiesta)
# ---------------------------------------------------------------------

NEWS_FEEDS = {
    "Il Sole 24 Ore": "https://www.ilsole24ore.com/rss/finanza.xml",
    "ANSA Economia": "https://www.ansa.it/sito/notizie/economia/economia_rss.xml",
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
}


def get_news():
    news = []
    for source, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                news.append(
                    {
                        "fonte": source,
                        "titolo": entry.get("title", ""),
                        "link": entry.get("link", ""),
                    }
                )
        except Exception:
            continue
    return news


# ---------------------------------------------------------------------
# 4. CALCOLO SENTIMENT SCORE (regole fisse, non IA generativa)
# ---------------------------------------------------------------------

def _trova_macro(macro, nome_contiene):
    for m in macro:
        if nome_contiene.lower() in m["nome"].lower():
            return m
    return None


def calculate_sentiment(market, macro):
    components = {}

    vix = market.get("VIX (volatilitÃ  USA)", {}).get("prezzo")
    if vix is not None:
        if vix < 20:
            components["volatilita"] = 100
        elif vix < 30:
            components["volatilita"] = 60
        else:
            components["volatilita"] = 20

    momentum_scores = []
    for name in ["FTSE MIB (Italia)", "S&P 500 (USA)", "Stoxx 600 (Eurozona)", "MSCI World ETF"]:
        d = market.get(name, {})
        if "sopra_media_50gg" in d:
            score = 50
            if d["sopra_media_50gg"]:
                score += 25
            if d["sopra_media_200gg"]:
                score += 25
            momentum_scores.append(score)
    if momentum_scores:
        components["momentum"] = sum(momentum_scores) / len(momentum_scores)

    spread = _trova_macro(macro, "spread rendimenti")
    if spread and spread.get("valore") is not None:
        components["curva_rendimenti"] = 20 if spread["valore"] < 0 else 80

    infl = _trova_macro(macro, "inflazione eurozona")
    if infl and infl.get("valore") is not None:
        distanza = abs(infl["valore"] - 2.0)
        components["inflazione"] = max(0, 100 - distanza * 25)

    if not components:
        return {"punteggio": None, "semaforo": "sconosciuto", "dettaglio": {}}

    punteggio = round(sum(components.values()) / len(components), 1)

    if punteggio >= 70:
        semaforo = "verde"
    elif punteggio >= 45:
        semaforo = "giallo"
    else:
        semaforo = "rosso"

    return {"punteggio": punteggio, "semaforo": semaforo, "dettaglio": components}


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def main():
    market = get_market_data()
    macro = get_macro_data()
    news = get_news()
    sentiment = calculate_sentiment(market, macro)

    output = {
        "aggiornato_il": datetime.datetime.utcnow().isoformat() + "Z",
        "sentiment": sentiment,
        "mercati": market,
        "macro": macro,
        "news": news,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("Dati salvati in docs/data.json")


if __name__ == "__main__":
    main()
