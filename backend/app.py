from datetime import datetime, timezone
from typing import List

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from transformers import pipeline

from collectors.reddit_collector import coletar_posts_reddit_json
from collectors.x_collector import coletar_tweets_x, coletar_feed_x
from db import Base, engine, SessionLocal
from models import MarketPoint, SocialPost

load_dotenv()

Base.metadata.create_all(bind=engine)

# ── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SentCrypto API",
    description="API de análise de sentimento do mercado de criptomoedas",
    version="1.0.0",
)

# ── BERT (IA) ───────────────────────────────────────────────────────────────
BERT_MODEL_NAME = "nlptown/bert-base-multilingual-uncased-sentiment"
sentiment_pipeline = None

try:
    print("Carregando modelo BERT de sentimento...")
    sentiment_pipeline = pipeline(
        "sentiment-analysis",
        model=BERT_MODEL_NAME,
        tokenizer=BERT_MODEL_NAME,
    )
    print("BERT carregado com sucesso.")
except Exception as e:
    print(f"Erro ao carregar BERT: {e}")

# ── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Dependência de banco ───────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Binance helpers ─────────────────────────────────────────────────────────
BINANCE_API_URL = "https://api.binance.com/api/v3/klines"


def fetch_binance_klines(symbol: str, interval: str = "1h", limit: int = 24):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(BINANCE_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Erro ao buscar dados na Binance: {e}"
        )


# ── Sentimento helpers ──────────────────────────────────────────────────────
def mapear_estrela_para_sentimento(label: str) -> str:
    """Converte label do modelo (ex: '1 star') em negativo/neutro/positivo."""
    if not label:
        return "neutro"
    if "1" in label or "2" in label:
        return "negativo"
    if "3" in label:
        return "neutro"
    return "positivo"


def sentimento_para_indice(sentimento: str) -> float:
    """Converte sentimento em índice numérico (0-1)."""
    if sentimento == "negativo":
        return 0.2
    if sentimento == "positivo":
        return 0.8
    return 0.5


def analisar_e_salvar_post(
    db: Session,
    moeda: str,
    fonte: str,
    texto: str,
    timestamp_post: datetime,
) -> SocialPost:
    """Analisa o texto com BERT e salva no SQLite."""
    if sentiment_pipeline is None:
        raise HTTPException(status_code=500, detail="Modelo BERT não carregado.")

    texto = (texto or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="Texto vazio.")

    result = sentiment_pipeline(texto, truncation=True, max_length=512)[0]
    label = result["label"]
    score = float(result["score"])
    sentimento = mapear_estrela_para_sentimento(label)

    post = SocialPost(
        moeda=moeda.upper(),
        fonte=fonte,
        texto=texto,
        sentimento=sentimento,
        score=score,
        timestamp_post=timestamp_post,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


# ── Schemas (Pydantic) ──────────────────────────────────────────────────────
class ColetaRedditRequest(BaseModel):
    moeda: str = "BTC"
    subreddits: List[str] = ["CryptoCurrency", "Bitcoin", "ethtrader"]
    limite_por_sub: int = 25
    ordenacao: str = "new"


class ColetaXRequest(BaseModel):
    moeda: str = "BTC"
    perfis: List[str] = ["whale_alert", "cabortopcripto"]
    limite_por_perfil: int = 20


class FeedXRequest(BaseModel):
    perfis: List[str] = ["whale_alert", "cabortopcripto"]
    limite_por_perfil: int = 30


class TextoParaAnalise(BaseModel):
    texto: str
    moeda: str = "BTC"


# ═══════════════════════════════════════════════════════════════════════════
#  ROTAS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/", tags=["health"])
def health_check():
    """Verifica se a API está no ar e se o BERT está carregado."""
    return {"status": "ok", "bert_carregado": sentiment_pipeline is not None}


# ── Sentimento atual (candle) ───────────────────────────────────────────────
@app.get("/sentimento", tags=["sentimento"])
def sentimento_atual(moeda: str = Query("BTC")):
    """Retorna o sentimento derivado do último candle da Binance."""
    symbol = f"{moeda.upper()}USDT"
    klines = fetch_binance_klines(symbol, interval="1h", limit=2)

    if not klines:
        raise HTTPException(status_code=404, detail="Nenhum dado encontrado.")

    ultimo = klines[-1]
    abertura = float(ultimo[1])
    fechamento = float(ultimo[4])
    variacao = (fechamento - abertura) / abertura if abertura else 0

    if variacao > 0.005:
        sentimento = "positivo"
    elif variacao < -0.005:
        sentimento = "negativo"
    else:
        sentimento = "neutro"

    ts = datetime.fromtimestamp(ultimo[0] / 1000, tz=timezone.utc)

    return {
        "moeda": moeda.upper(),
        "sentimento_atual": sentimento,
        "indice_sentimento": round(sentimento_para_indice(sentimento), 2),
        "preco": round(fechamento, 2),
        "variacao_percentual": round(variacao * 100, 4),
        "ultimo_update": ts.isoformat(),
    }


# ── Histórico ao vivo (Binance) ────────────────────────────────────────────
@app.get("/historico-sentimento", tags=["historico"])
def historico_sentimento(
    moeda: str = Query("BTC"),
    limite: int = Query(24, ge=1, le=100),
):
    """Retorna histórico de preço + sentimento via Binance (ao vivo)."""
    symbol = f"{moeda.upper()}USDT"
    klines = fetch_binance_klines(symbol, interval="1h", limit=limite)

    pontos = []
    for k in klines:
        abertura = float(k[1])
        fechamento = float(k[4])
        variacao = (fechamento - abertura) / abertura if abertura else 0

        if variacao > 0.005:
            sent = "positivo"
        elif variacao < -0.005:
            sent = "negativo"
        else:
            sent = "neutro"

        ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        pontos.append(
            {
                "timestamp": ts.isoformat(),
                "preco": round(fechamento, 2),
                "indice_sentimento": sentimento_para_indice(sent),
            }
        )

    return {"moeda": moeda.upper(), "pontos": pontos}


# ── Histórico salvo no banco (market_points) ───────────────────────────────
@app.get("/historico-db", tags=["historico"])
def historico_db(
    moeda: str = Query("BTC"),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Retorna histórico salvo na tabela market_points."""
    registros = (
        db.query(MarketPoint)
        .filter(MarketPoint.moeda == moeda.upper())
        .order_by(MarketPoint.timestamp.desc())
        .limit(limite)
        .all()
    )
    registros.reverse()

    pontos = [
        {
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "preco": round(r.preco, 2) if r.preco else None,
            "indice_sentimento": (
                round(r.indice_sentimento, 2) if r.indice_sentimento else None
            ),
        }
        for r in registros
    ]
    return {"moeda": moeda.upper(), "pontos": pontos}


# ── Histórico social (social_posts) ────────────────────────────────────────
@app.get("/historico-social", tags=["historico"])
def historico_social(
    moeda: str = Query("BTC"),
    fonte: str = Query("Reddit"),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Retorna histórico de sentimento dos posts sociais agrupado por hora."""
    posts = (
        db.query(SocialPost)
        .filter(
            SocialPost.moeda == moeda.upper(),
            SocialPost.fonte == fonte,
        )
        .order_by(SocialPost.timestamp_post.desc())
        .limit(limite)
        .all()
    )
    posts.reverse()

    agrupado: dict = {}
    for p in posts:
        hora = p.timestamp_post.replace(minute=0, second=0, microsecond=0)
        chave = hora.isoformat()
        if chave not in agrupado:
            agrupado[chave] = {"indices": [], "timestamp": chave}
        agrupado[chave]["indices"].append(sentimento_para_indice(p.sentimento))

    pontos = []
    for grupo in agrupado.values():
        media = sum(grupo["indices"]) / len(grupo["indices"])
        pontos.append(
            {
                "timestamp": grupo["timestamp"],
                "preco": None,
                "indice_sentimento": round(media, 2),
            }
        )

    return {"moeda": moeda.upper(), "fonte": fonte, "pontos": pontos}


# ── Coleta Reddit ──────────────────────────────────────────────────────────
@app.post("/coletar/reddit", tags=["coleta"])
def coletar_reddit(body: ColetaRedditRequest, db: Session = Depends(get_db)):
    """Coleta posts do Reddit, analisa sentimento com BERT e salva no banco."""
    if sentiment_pipeline is None:
        raise HTTPException(status_code=500, detail="Modelo BERT não carregado.")

    posts_brutos = coletar_posts_reddit_json(
        subreddits=body.subreddits,
        moeda=body.moeda,
        limite_por_sub=body.limite_por_sub,
        ordenacao=body.ordenacao,
    )

    salvos = 0
    erros = 0
    for raw in posts_brutos:
        try:
            analisar_e_salvar_post(
                db=db,
                moeda=body.moeda,
                fonte="Reddit",
                texto=raw["texto"],
                timestamp_post=raw["timestamp_post"],
            )
            salvos += 1
        except Exception:
            erros += 1

    return {
        "mensagem": f"Coleta finalizada: {salvos} posts salvos, {erros} erros.",
        "total_coletados": len(posts_brutos),
        "salvos": salvos,
        "erros": erros,
    }


# ── Feed do X (timeline em tempo real) ──────────────────────────────────────
@app.post("/feed/x", tags=["feed"])
def feed_x(body: FeedXRequest):
    """Puxa tweets recentes de perfis específicos e retorna com análise BERT."""
    try:
        tweets = coletar_feed_x(
            perfis=body.perfis,
            limite_por_perfil=body.limite_por_perfil,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Analisa sentimento de cada tweet (se BERT disponível)
    resultado = []
    for tw in tweets:
        sentimento = None
        indice = None
        score_bert = None

        if sentiment_pipeline and tw["texto"]:
            try:
                r = sentiment_pipeline(
                    tw["texto"], truncation=True, max_length=512
                )[0]
                sentimento = mapear_estrela_para_sentimento(r["label"])
                indice = sentimento_para_indice(sentimento)
                score_bert = round(float(r["score"]), 4)
            except Exception:
                pass

        resultado.append({
            "texto": tw["texto"],
            "perfil": tw["perfil"],
            "nome_exibicao": tw.get("nome_exibicao", tw["perfil"]),
            "avatar": tw.get("avatar"),
            "timestamp": tw["timestamp_post"],
            "tweet_id": tw.get("tweet_id"),
            "likes": tw.get("likes", 0),
            "retweets": tw.get("retweets", 0),
            "replies": tw.get("replies", 0),
            "sentimento": sentimento,
            "indice_sentimento": indice,
            "score_bert": score_bert,
        })

    return {
        "total": len(resultado),
        "perfis": body.perfis,
        "tweets": resultado,
    }


# ── Coleta X (Twitter) ─────────────────────────────────────────────────────
@app.post("/coletar/x", tags=["coleta"])
def coletar_x(body: ColetaXRequest, db: Session = Depends(get_db)):
    """Coleta tweets de perfis específicos do X, analisa sentimento e salva."""
    if sentiment_pipeline is None:
        raise HTTPException(status_code=500, detail="Modelo BERT não carregado.")

    try:
        tweets_brutos = coletar_tweets_x(
            perfis=body.perfis,
            moeda=body.moeda,
            limite_por_perfil=body.limite_por_perfil,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    salvos = 0
    erros = 0
    for raw in tweets_brutos:
        try:
            analisar_e_salvar_post(
                db=db,
                moeda=body.moeda,
                fonte="X",
                texto=raw["texto"],
                timestamp_post=raw["timestamp_post"],
            )
            salvos += 1
        except Exception:
            erros += 1

    return {
        "mensagem": f"Coleta X finalizada: {salvos} tweets salvos, {erros} erros.",
        "total_coletados": len(tweets_brutos),
        "salvos": salvos,
        "erros": erros,
        "perfis_consultados": body.perfis,
    }


# ── Análise de texto livre ─────────────────────────────────────────────────
@app.post("/analisar-texto", tags=["sentimento"])
def analisar_texto(body: TextoParaAnalise):
    """Analisa o sentimento de um texto livre com BERT (sem salvar no banco)."""
    if sentiment_pipeline is None:
        raise HTTPException(status_code=500, detail="Modelo BERT não carregado.")

    texto = (body.texto or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="Texto vazio.")

    result = sentiment_pipeline(texto, truncation=True, max_length=512)[0]
    sentimento = mapear_estrela_para_sentimento(result["label"])

    return {
        "texto": texto[:200],
        "sentimento": sentimento,
        "indice": sentimento_para_indice(sentimento),
        "score_bert": round(float(result["score"]), 4),
        "label_bert": result["label"],
    }
