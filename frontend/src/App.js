import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import "./App.css";

const MOEDAS = ["BTC", "ETH", "SOL", "DOGE"];
const FONTES = {
  api: "Dados ao vivo (Binance)",
  db: "Histórico salvo (SQLite)",
  reddit: "Reddit (posts)",
  x: "X / Twitter (perfis)",
};

function App() {
  const [moedaSelecionada, setMoedaSelecionada] = useState("BTC");
  const [fonteDados, setFonteDados] = useState("api");
  const [historico, setHistorico] = useState([]);
  const [sentimentoAtual, setSentimentoAtual] = useState(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(null);
  const [feedTweets, setFeedTweets] = useState([]);
  const [feedLoading, setFeedLoading] = useState(false);
  const [perfisX, setPerfisX] = useState("whale_alert, cabortopcripto");

  const carregarDados = async (moeda, fonte) => {
    setLoading(true);
    setErro(null);

    try {
      // 1) Busca o histórico principal (sentimento, depende da fonte)
      const urlHistorico =
        fonte === "api"
          ? `http://127.0.0.1:8000/historico-sentimento?moeda=${moeda}`
          : fonte === "db"
            ? `http://127.0.0.1:8000/historico-db?moeda=${moeda}`
            : fonte === "x"
              ? `http://127.0.0.1:8000/historico-social?moeda=${moeda}&fonte=X`
              : `http://127.0.0.1:8000/historico-social?moeda=${moeda}&fonte=Reddit`;

      const resHist = await fetch(urlHistorico);
      const dadosHist = await resHist.json();

      // 2) Se for reddit: busca também preço da Binance pra manter o gráfico completo
      let mapaPrecoPorHora = {};

      if (fonte === "reddit" || fonte === "x") {
        const resPreco = await fetch(
          `http://127.0.0.1:8000/historico-sentimento?moeda=${moeda}`,
        );
        const dadosPreco = await resPreco.json();

        (dadosPreco.pontos || []).forEach((p) => {
          const key = new Date(p.timestamp).toLocaleTimeString("pt-BR", {
            hour: "2-digit",
            minute: "2-digit",
          });
          mapaPrecoPorHora[key] = p.preco;
        });
      }

      // 3) Formata e (se reddit) injeta o preço
      const formatados = (dadosHist.pontos || []).map((ponto) => {
        const key = new Date(ponto.timestamp).toLocaleTimeString("pt-BR", {
          hour: "2-digit",
          minute: "2-digit",
        });

        return {
          timestamp: key,
          preco:
            fonte === "reddit" || fonte === "x"
              ? (mapaPrecoPorHora[key] ?? null)
              : ponto.preco,
          indice_sentimento: ponto.indice_sentimento,
        };
      });

      setHistorico(formatados);

      // Sentimento atual (candle) - mantém sempre do endpoint ao vivo
      const resSent = await fetch(
        `http://127.0.0.1:8000/sentimento?moeda=${moeda}`,
      );
      if (!resSent.ok)
        throw new Error(`Erro ${resSent.status} ao buscar sentimento atual`);

      const dadosSent = await resSent.json();
      setSentimentoAtual(dadosSent);

      setLoading(false);
    } catch (e) {
      console.error(e);
      setErro("Erro ao carregar dados. Verifique se o backend está rodando.");
      setLoading(false);
    }
  };

  useEffect(() => {
    carregarDados(moedaSelecionada, fonteDados);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moedaSelecionada, fonteDados]);

  const carregarFeedX = async () => {
    setFeedLoading(true);
    setErro(null);
    try {
      const listaPerfis = perfisX
        .split(",")
        .map((p) => p.trim().replace("@", ""))
        .filter(Boolean);

      const res = await fetch("http://127.0.0.1:8000/feed/x", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          perfis: listaPerfis,
          limite_por_perfil: 30,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Erro ao buscar feed");
      }

      const data = await res.json();
      setFeedTweets(data.tweets || []);
    } catch (e) {
      console.error(e);
      setErro(`Falha ao carregar feed do X: ${e.message}`);
    } finally {
      setFeedLoading(false);
    }
  };

  const corSentimentoTweet = (sent) =>
    sent === "positivo"
      ? "#22c55e"
      : sent === "negativo"
        ? "#ef4444"
        : "#eab308";

  const corSentimento =
    sentimentoAtual?.sentimento_atual === "positivo"
      ? "#22c55e"
      : sentimentoAtual?.sentimento_atual === "negativo"
        ? "#ef4444"
        : "#eab308";

  const descricaoFonte =
    fonteDados === "api"
      ? "Usando dados em tempo real da Binance (endpoint /historico-sentimento)."
      : fonteDados === "db"
        ? "Usando dados armazenados no SQLite (endpoint /historico-db)."
        : fonteDados === "reddit"
          ? "Usando posts do Reddit analisados por BERT (endpoint /historico-social)."
          : "Usando tweets do X de perfis específicos, analisados por BERT.";

  return (
    <div className="app">
      {/* SIDEBAR */}
      <aside className="sidebar">
        <h2 className="logo">SentCrypto</h2>

        <p className="sidebar-label">Moedas</p>
        <div className="sidebar-list">
          {MOEDAS.map((m) => (
            <button
              key={m}
              className={`sidebar-item ${
                moedaSelecionada === m ? "sidebar-item--active" : ""
              }`}
              onClick={() => setMoedaSelecionada(m)}
            >
              {m}
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          <p>Projeto TCC</p>
          <span className="sidebar-tag">IA • Análise de Sentimento</span>
        </div>
      </aside>

      {/* CONTEÚDO PRINCIPAL */}
      <main className="main">
        <header className="header">
          <div>
            <h1>Sentimento do Mercado de Criptomoedas</h1>
            <p className="subtitle">
              Monitorando humor das redes sociais e variação de preço para{" "}
              <span className="highlight">{moedaSelecionada}</span>
            </p>
          </div>
        </header>

        {/* Toggle de fonte de dados */}
        <section className="controls">
          <div className="toggle-group">
            {Object.entries(FONTES).map(([key, label]) => (
              <button
                key={key}
                className={`toggle-button ${
                  fonteDados === key ? "toggle-button--active" : ""
                }`}
                onClick={() => setFonteDados(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <p className="controls-hint">{descricaoFonte}</p>

          {/* Botão extra: coletar Reddit */}
          {fonteDados === "reddit" && (
            <button
              className="toggle-button"
              onClick={async () => {
                try {
                  setLoading(true);
                  setErro(null);

                  await fetch("http://127.0.0.1:8000/coletar/reddit", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      moeda: moedaSelecionada,
                      subreddits: ["CryptoCurrency", "Bitcoin"],
                      limite_por_sub: 20,
                      ordenacao: "new",
                    }),
                  });

                  await carregarDados(moedaSelecionada, "reddit");
                } catch (e) {
                  console.error(e);
                  setErro("Falha ao coletar posts do Reddit.");
                  setLoading(false);
                }
              }}
            >
              Coletar Reddit agora
            </button>
          )}

          {/* Botão extra: coletar X */}
          {fonteDados === "x" && (
            <div className="x-controls">
              <label className="x-label">
                Perfis do X (separados por vírgula):
              </label>
              <input
                className="x-input"
                type="text"
                value={perfisX}
                onChange={(e) => setPerfisX(e.target.value)}
                placeholder="whale_alert, elonmusk"
              />
              <div className="x-buttons">
                <button
                  className="toggle-button"
                  disabled={feedLoading}
                  onClick={carregarFeedX}
                >
                  {feedLoading ? "Carregando feed..." : "Carregar Feed do X"}
                </button>
                <button
                  className="toggle-button"
                  onClick={async () => {
                    try {
                      setLoading(true);
                      setErro(null);
                      const listaPerfis = perfisX
                        .split(",")
                        .map((p) => p.trim().replace("@", ""))
                        .filter(Boolean);

                      await fetch("http://127.0.0.1:8000/coletar/x", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          moeda: moedaSelecionada,
                          perfis: listaPerfis,
                          limite_por_perfil: 20,
                        }),
                      });

                      await carregarDados(moedaSelecionada, "x");
                    } catch (e) {
                      console.error(e);
                      setErro("Falha ao coletar tweets do X.");
                      setLoading(false);
                    }
                  }}
                >
                  Analisar sentimento e salvar
                </button>
              </div>
            </div>
          )}
        </section>

        {erro && <div className="error">{erro}</div>}
        {loading && !erro && <div className="loading">Carregando dados...</div>}

        {!loading && !erro && (
          <>
            {/* CARDS SUPERIORES */}
            <section className="cards">
              <div className="card">
                <p className="card-label">Moeda</p>
                <p className="card-value">{moedaSelecionada}</p>
              </div>

              <div className="card">
                <p className="card-label">Sentimento atual (candle)</p>
                <p className="card-value" style={{ color: corSentimento }}>
                  {sentimentoAtual?.sentimento_atual}
                </p>
                <p className="card-extra">
                  Índice: {sentimentoAtual?.indice_sentimento}
                </p>
              </div>

              <div className="card">
                <p className="card-label">Última atualização</p>
                <p className="card-value small">
                  {sentimentoAtual?.ultimo_update
                    ? new Date(sentimentoAtual.ultimo_update).toLocaleString(
                        "pt-BR",
                      )
                    : "-"}
                </p>
              </div>
            </section>

            {/* GRÁFICO */}
            <section className="chart-section">
              <div className="chart-header">
                <div>
                  <h2>Histórico (Preço x Sentimento)</h2>
                  <span className="chart-pill">
                    Fonte: {FONTES[fonteDados]}
                  </span>
                </div>
              </div>

              <div className="chart-wrapper">
                {historico.length === 0 ? (
                  <p className="no-data">
                    Nenhum dado encontrado para esta combinação de moeda +
                    fonte.
                  </p>
                ) : (
                  <ResponsiveContainer>
                    <LineChart data={historico}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="timestamp" stroke="#9ca3af" />

                      {/* eixo do preço */}
                      <YAxis
                        yAxisId="left"
                        stroke="#60a5fa"
                        tickFormatter={(v) =>
                          v == null ? "" : Number(v).toFixed(0)
                        }
                      />

                      {/* eixo do sentimento */}
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        stroke="#34d399"
                        domain={[0, 1]}
                      />

                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#111827",
                          border: "1px solid #374151",
                          borderRadius: 8,
                        }}
                      />
                      <Legend />

                      {/* Linha de preço - só faz sentido se tiver preço */}
                      <Line
                        yAxisId="left"
                        type="monotone"
                        dataKey="preco"
                        name="Preço"
                        stroke="#60a5fa"
                        strokeWidth={2}
                        dot={false}
                        connectNulls={false}
                      />

                      {/* Linha de sentimento - sempre */}
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="indice_sentimento"
                        name="Sentimento"
                        stroke="#34d399"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>

            {/* FEED DO X — só aparece na aba X */}
            {fonteDados === "x" && feedTweets.length > 0 && (
              <section className="feed-section">
                <div className="feed-header">
                  <h2>Timeline do X</h2>
                  <span className="chart-pill">{feedTweets.length} tweets</span>
                </div>
                <div className="feed-list">
                  {feedTweets.map((tw, i) => (
                    <div key={tw.tweet_id || i} className="tweet-card">
                      <div className="tweet-top">
                        <div className="tweet-avatar">
                          {tw.avatar ? (
                            <img src={tw.avatar} alt="" />
                          ) : (
                            <div className="tweet-avatar-placeholder">
                              {(tw.nome_exibicao ||
                                tw.perfil ||
                                "?")[0].toUpperCase()}
                            </div>
                          )}
                        </div>
                        <div className="tweet-meta">
                          <span className="tweet-name">
                            {tw.nome_exibicao || tw.perfil}
                          </span>
                          <span className="tweet-handle">{tw.perfil}</span>
                          <span className="tweet-dot">·</span>
                          <span className="tweet-time">
                            {new Date(tw.timestamp).toLocaleString("pt-BR", {
                              day: "2-digit",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        </div>
                      </div>

                      <p className="tweet-text">{tw.texto}</p>

                      <div className="tweet-bottom">
                        <div className="tweet-stats">
                          <span title="Respostas">💬 {tw.replies}</span>
                          <span title="Retweets">🔁 {tw.retweets}</span>
                          <span title="Curtidas">❤️ {tw.likes}</span>
                        </div>
                        {tw.sentimento && (
                          <span
                            className="tweet-sentiment"
                            style={{
                              backgroundColor: corSentimentoTweet(
                                tw.sentimento,
                              ),
                            }}
                          >
                            {tw.sentimento} ({tw.score_bert})
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default App;
