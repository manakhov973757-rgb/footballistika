import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  Bot,
  Brain,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Database,
  Flag,
  Goal,
  Home,
  Info,
  Layers3,
  Loader2,
  Shield,
  Sparkles,
  Swords,
  Target,
  TrendingUp,
  Trophy,
  Zap,
} from "lucide-react";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const ANALYSIS_STAGES = [
  { label: "Загружаем форму команд", icon: "01" },
  { label: "Считаем REAL xG", icon: "02" },
  { label: "Сверяем реальные коэффициенты", icon: "03" },
  { label: "Ищем Value и Confidence", icon: "04" },
  { label: "Проверяем угловые", icon: "05" },
  { label: "Анализируем жёлтые карточки и арбитра", icon: "06" },
];

const teamInitials = (name = "") => {
  const words = String(name).trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "FC";
  const ignored = new Set(["fc", "cf", "afc", "sc", "club", "de", "calcio", "balompié"]);
  const useful = words.filter((w) => !ignored.has(w.toLowerCase()));
  const source = useful.length ? useful : words;
  return source.slice(0, 2).map((w) => w[0]).join("").toUpperCase();
};

function TeamCrest({ src, name, side = "home" }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={`team-crest ${side}`}>
      {src && !failed ? (
        <img src={src} alt={`${name} crest`} onError={() => setFailed(true)} />
      ) : (
        <span>{teamInitials(name)}</span>
      )}
    </div>
  );
}

function LeagueBadge({ src, name, code }) {
  return (
    <div className="league-badge">
      <div className="league-logo">
        {src ? <img src={src} alt={`${name || "League"} logo`} /> : <Trophy size={16} />}
      </div>
      <span>{name || "Football"}</span>
      {code ? <small>{code}</small> : null}
    </div>
  );
}

const pct = (value, fallback = 0) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const number = (value, digits = 2) => {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
};

const percentText = (value) => `${pct(value).toFixed(1)}%`;

const valuePercent = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const percentage = Math.abs(n) <= 2 ? n * 100 : n;
  return `${percentage >= 0 ? "+" : ""}${percentage.toFixed(1)}%`;
};

const valueNumber = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.abs(n) <= 2 ? n * 100 : n;
};


const prettyBetLabel = (bet) => {
  const selection = String(bet?.selection || bet?.bet_label || bet?.label || bet?.pick || "").trim();
  const market = String(bet?.market || bet?.market_key || "").trim();

  const normalize = (value) =>
    String(value || "")
      .trim()
      .toLowerCase()
      .replace(/ё/g, "е")
      .replace(/[–—]/g, "-")
      .replace(/\s+/g, " ");

  const candidates = [selection, market].filter(Boolean);

  const exactMap = {
    "over_25": "ТБ 2.5",
    "over25": "ТБ 2.5",
    "o2.5": "ТБ 2.5",
    "тб 2.5": "ТБ 2.5",
    "тб2.5": "ТБ 2.5",
    "тотал больше 2.5": "ТБ 2.5",
    "больше 2.5": "ТБ 2.5",

    "under_25": "ТМ 2.5",
    "under25": "ТМ 2.5",
    "u2.5": "ТМ 2.5",
    "тм 2.5": "ТМ 2.5",
    "тм2.5": "ТМ 2.5",
    "тотал меньше 2.5": "ТМ 2.5",
    "меньше 2.5": "ТМ 2.5",

    "home_win": "П1",
    "home": "П1",
    "п1": "П1",
    "победа хозяев": "П1",

    "draw": "Х",
    "x": "Х",
    "х": "Х",
    "ничья": "Х",

    "away_win": "П2",
    "away": "П2",
    "п2": "П2",
    "победа гостей": "П2",

    "double_home": "1Х",
    "1x": "1Х",
    "1х": "1Х",
    "хозяева не проиграют": "1Х",

    "double_away": "Х2",
    "x2": "Х2",
    "х2": "Х2",
    "гости не проиграют": "Х2",

    "btts_yes": "ОЗ — Да",
    "btts yes": "ОЗ — Да",
    "оз да": "ОЗ — Да",
    "оз - да": "ОЗ — Да",
    "обе забьют да": "ОЗ — Да",

    "btts_no": "ОЗ — Нет",
    "btts no": "ОЗ — Нет",
    "оз нет": "ОЗ — Нет",
    "оз - нет": "ОЗ — Нет",
    "обе забьют нет": "ОЗ — Нет",
  };

  for (const candidate of candidates) {
    const normalized = normalize(candidate);
    const key = normalized.replace(/\s+/g, "_");
    if (exactMap[normalized]) return exactMap[normalized];
    if (exactMap[key]) return exactMap[key];

    // Totals with arbitrary line.
    const overMatch =
      normalized.match(/(?:over|больше|тб)\s*([0-9]+(?:[.,][0-9]+)?)/i) ||
      normalized.match(/([0-9]+(?:[.,][0-9]+)?)\s*(?:over|больше)/i);
    if (overMatch && !normalized.includes("corner") && !normalized.includes("углов")) {
      return `ТБ ${overMatch[1].replace(",", ".")}`;
    }

    const underMatch =
      normalized.match(/(?:under|меньше|тм)\s*([0-9]+(?:[.,][0-9]+)?)/i) ||
      normalized.match(/([0-9]+(?:[.,][0-9]+)?)\s*(?:under|меньше)/i);
    if (underMatch && !normalized.includes("corner") && !normalized.includes("углов")) {
      return `ТМ ${underMatch[1].replace(",", ".")}`;
    }

    // Corners.
    if (normalized.includes("corner") || normalized.includes("углов")) {
      const line = normalized.match(/[0-9]+(?:[.,][0-9]+)?/);
      const lineText = line ? line[0].replace(",", ".") : "";
      if (normalized.includes("under") || normalized.includes("меньше") || normalized.includes("тм")) {
        return `ТМ ${lineText} угловых`.trim();
      }
      if (normalized.includes("over") || normalized.includes("больше") || normalized.includes("тб")) {
        return `ТБ ${lineText} угловых`.trim();
      }
      return lineText ? `Тотал ${lineText} угловых` : "Угловые";
    }
  }

  // If backend already returned a readable Russian label, keep it.
  if (selection && /[А-Яа-яЁё]/.test(selection)) return selection;
  if (market && /[А-Яа-яЁё]/.test(market)) return market;

  return "—";
};

const prettyBetDescription = (bet) => {
  const label = prettyBetLabel(bet);
  if (label === "ТБ 2.5") return "Больше 2.5 голов в матче";
  if (label === "ТМ 2.5") return "Меньше 2.5 голов в матче";
  if (label === "П1") return "Победа хозяев";
  if (label === "П2") return "Победа гостей";
  if (label === "Х" || label === "X") return "Ничья";
  if (label === "1Х" || label === "1X") return "Хозяева не проиграют";
  if (label === "Х2" || label === "X2") return "Гости не проиграют";
  if (label === "ОЗ — Да") return "Обе команды забьют";
  if (label === "ОЗ — Нет") return "Хотя бы одна команда не забьёт";
  return "Лучшая ставка по оценке модели";
};

function Progress({ value = 0, tone = "green" }) {
  const width = Math.max(0, Math.min(100, pct(value)));
  return (
    <div className={`progress ${tone}`}>
      <div className="progress-fill" style={{ width: `${width}%` }} />
    </div>
  );
}

function LogoMark() {
  return (
    <div className="logo-mark" aria-hidden="true">
      <div className="logo-ball">⚽</div>
    </div>
  );
}

function SectionTitle({ icon, title, subtitle, badge }) {
  return (
    <div className="section-title-row">
      <div className="section-title-icon">{icon}</div>
      <div className="section-title-copy">
        <h3>{title}</h3>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {badge ? <span className="section-chip">{badge}</span> : null}
    </div>
  );
}

function FormPill({ result }) {
  const value = String(result || "—").toUpperCase();
  const cls = value === "W" ? "win" : value === "L" ? "loss" : value === "D" ? "draw" : "";
  return <span className={`form-pill ${cls}`}>{value}</span>;
}

function OddsStatus({ bet }) {
  const label = String(bet?.status || bet?.grade || bet?.recommendation || "").toUpperCase();
  if (label.includes("STRONG")) return <span className="status-badge strong">🔥 СИЛЬНАЯ СТАВКА</span>;
  if (label.includes("VALUE")) return <span className="status-badge value">💎 ВАЛУЙНАЯ СТАВКА</span>;
  if (valueNumber(bet?.value) >= 10 && pct(bet?.confidence) >= 50) {
    return <span className="status-badge strong">🔥 СИЛЬНАЯ СТАВКА</span>;
  }
  if (valueNumber(bet?.value) >= 3) return <span className="status-badge value">💎 ВАЛУЙНАЯ СТАВКА</span>;
  return <span className="status-badge neutral">НЕТ СТАВКИ</span>;
}


const monthNow = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

const statusMeta = (status) => {
  if (status === "win") return { label: "ВЫИГРЫШ", cls: "win" };
  if (status === "loss") return { label: "ПРОИГРЫШ", cls: "loss" };
  if (status === "void") return { label: "ВОЗВРАТ", cls: "void" };
  if (status === "no_bet") return { label: "НЕТ СТАВКИ", cls: "neutral" };
  return { label: "ОЖИДАЕТ", cls: "pending" };
};

function StatisticsPage() {
  const [month, setMonth] = useState(monthNow());
  const [data, setData] = useState(null);
  const [loadingStats, setLoadingStats] = useState(false);
  const [statsError, setStatsError] = useState("");

  async function loadStats(targetMonth = month) {
    setLoadingStats(true);
    setStatsError("");

    const monthParam = encodeURIComponent(targetMonth);
    const endpoints = [
      `${API_URL}/statistics?month=${monthParam}`,
      `${API_URL}/statistics/raw?month=${monthParam}`,
    ];

    let lastError = null;

    try {
      for (const endpoint of endpoints) {
        try {
          const response = await fetch(endpoint, { cache: "no-store" });
          const json = await response.json();

          if (!response.ok) {
            throw new Error(json?.detail || `Backend error: ${response.status}`);
          }

          setData(json);
          lastError = null;
          break;
        } catch (err) {
          lastError = err;
          console.warn("Statistics endpoint failed:", endpoint, err);
        }
      }

      if (lastError) throw lastError;
    } catch (err) {
      setStatsError(err?.message || "Не удалось загрузить статистику.");
    } finally {
      setLoadingStats(false);
    }
  }

  useEffect(() => { loadStats(month); }, [month]);

  const summary = data?.summary || data?.stats || {};
  const bets = data?.bets || data?.rows || data?.items || [];
  const profit = Number(summary.profit_units || 0);

  return (
    <main className="page-wrap stats-page">
      <section className="stats-hero">
        <div>
          <span className="hero-kicker"><Trophy size={16} /> BET OF THE DAY TRACKER</span>
          <h1>Статистика <span>ставок дня</span></h1>
          <p>Каждая ставка дня фиксируется автоматически. После финального свистка система проверяет счёт и пересчитывает месячный профит.</p>
        </div>
        <div className="stats-month-control">
          <label htmlFor="stats-month">Месяц</label>
          <input id="stats-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          <button type="button" onClick={() => loadStats(month)} disabled={loadingStats}>
            {loadingStats ? <Loader2 className="spin" size={17} /> : <BarChart3 size={17} />} Обновить
          </button>
        </div>
      </section>

      {statsError ? (
        <div className="error-banner">
          {statsError}
          <button type="button" onClick={() => loadStats(month)} style={{ marginLeft: 12 }}>
            Повторить
          </button>
        </div>
      ) : null}

      <section className="stats-summary-grid">
        <div className={`stats-kpi profit ${profit >= 0 ? "positive" : "negative"}`}>
          <span>Профит за месяц</span>
          <strong>{profit >= 0 ? "+" : ""}{profit.toFixed(2)} u</strong>
          <small>при фиксированной ставке 1 unit</small>
        </div>
        <div className="stats-kpi"><span>ROI</span><strong>{Number(summary.roi_percent || 0).toFixed(1)}%</strong><small>прибыль / сумма ставок</small></div>
        <div className="stats-kpi"><span>Выигрыши</span><strong>{summary.wins || 0}</strong><small>из {summary.bets_settled || 0} рассчитанных</small></div>
        <div className="stats-kpi"><span>Win rate</span><strong>{Number(summary.win_rate || 0).toFixed(1)}%</strong><small>{summary.losses || 0} проигрышей</small></div>
        <div className="stats-kpi"><span>Ожидают</span><strong>{summary.pending || 0}</strong><small>матчи ещё не рассчитаны</small></div>
        <div className="stats-kpi"><span>Проанализировано</span><strong>{summary.matches_analyzed || 0}</strong><small>матчей за выбранный месяц</small></div>
      </section>

      <section className="panel-card stats-journal-card">
        <SectionTitle icon={<Database size={20} />} title="Журнал ставок дня" subtitle="Результат фиксируется автоматически по итоговому счёту" badge={`${bets.length} матчей`} />
        <div className="value-table-wrap stats-table-wrap">
          <table className="value-table stats-table">
            <thead><tr><th>Дата</th><th>Матч</th><th>Ставка дня</th><th>Кэф</th><th>Результат</th><th>Счёт</th><th>Профит</th></tr></thead>
            <tbody>
              {bets.map((bet) => {
                const meta = statusMeta(bet.status);
                const rawDate = bet.kickoff_utc || bet.kickoff || bet.match_date || bet.created_at || null;
                const date = rawDate ? new Date(rawDate) : null;
                const profitValue = Number(bet.profit || 0);
                return (
                  <tr key={bet.id}>
                    <td>{date ? date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) : "—"}<small>{date ? date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : ""}</small></td>
                    <td><strong>{bet.home_team} — {bet.away_team}</strong><small>{bet.league || ""}</small></td>
                    <td><strong>{prettyBetLabel(bet)}</strong><small>{prettyBetDescription(bet)}</small></td>
                    <td><strong>{bet.odds ?? bet.coefficient ?? bet.price ?? "—"}</strong></td>
                    <td><span className={`bet-result-badge ${meta.cls}`}>{meta.label}</span></td>
                    <td><strong>{bet.home_score != null && bet.away_score != null ? `${bet.home_score}:${bet.away_score}` : "—"}</strong></td>
                    <td className={profitValue > 0 ? "positive" : profitValue < 0 ? "negative" : ""}>{bet.status === "win" || bet.status === "loss" || bet.status === "void" ? `${profitValue > 0 ? "+" : ""}${profitValue.toFixed(2)} u` : "—"}</td>
                  </tr>
                );
              })}
              {!bets.length && !loadingStats ? <tr><td colSpan="7" className="empty-table">В этом месяце пока нет зафиксированных ставок дня.</td></tr> : null}
              {loadingStats && !bets.length ? <tr><td colSpan="7" className="empty-table"><Loader2 className="spin inline-spinner" size={18} /> Проверяем результаты матчей...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function AboutPage() {
  return (
    <main className="page-wrap about-page">
      <section className="stats-hero about-hero">
        <div>
          <span className="hero-kicker"><Info size={16} /> FOOTBALLISTIKA</span>
          <h1>О <span>проекте</span></h1>
          <p>Footballistika объединяет форму команд, REAL xG, Poisson-модель, реальные букмекерские коэффициенты, Value, Confidence и анализ угловых в одном понятном интерфейсе.</p>
        </div>
      </section>
      <section className="about-grid">
        <div className="panel-card"><BarChart3 size={25} /><h3>Реальные данные</h3><p>Используем историю матчей, xG, форму, домашние/выездные показатели и доступные коэффициенты.</p></div>
        <div className="panel-card"><Target size={25} /><h3>Value прежде всего</h3><p>Сайт не ищет ставку ради ставки. Главная рекомендация появляется только там, где модель видит ценность.</p></div>
        <div className="panel-card"><Database size={25} /><h3>Проверяемый результат</h3><p>Ставки дня сохраняются в журнале. После матча результат и профит рассчитываются автоматически.</p></div>
      </section>
    </main>
  );
}

function App() {
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState(0);
  const [error, setError] = useState("");
  const [activePage, setActivePage] = useState("home");
  const resultsRef = useRef(null);

  useEffect(() => {
    if (!loading) {
      setLoadingStage(0);
      return undefined;
    }
    const timer = window.setInterval(() => {
      setLoadingStage((current) => Math.min(current + 1, ANALYSIS_STAGES.length - 1));
    }, 1100);
    return () => window.clearInterval(timer);
  }, [loading]);

  async function analyzeMatch() {
    if (!homeTeam.trim() || !awayTeam.trim()) return;
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          home_team: homeTeam.trim(),
          away_team: awayTeam.trim(),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || `Backend error: ${response.status}`);
      if (data?.status !== "success") throw new Error(data?.message || "Analysis failed");
      setResult(data);
      window.setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 120);
    } catch (err) {
      console.error(err);
      setError(err?.message || "Не удалось получить анализ. Проверь backend на порту 8000.");
    } finally {
      setLoading(false);
    }
  }

  function onEnter(event) {
    if (event.key === "Enter") analyzeMatch();
  }

  const prediction = result?.prediction || {};
  const xg = result?.xg || {};
  const goals = result?.goals || {};
  const btts = result?.btts || {};
  const odds = result?.odds || {};
  const corners = result?.corners || {};
  const cards = result?.cards || {};
  const markets = result?.betting_markets || [];
  // "Ставка дня" должна строго совпадать с финальной ставкой модели.
  // best_overall в backend может содержать сырой объект (например, corner/football)
  // и не является источником для главной футбольной рекомендации на UI.
  const bestBet = result?.best_bet || markets?.[0] || null;
  const ai = result?.ai_assessment || {};

  const strongestMarket = useMemo(() => {
    if (!bestBet) return null;
    const selection = bestBet.selection || bestBet.market || "Главная ставка";
    const probability = pct(bestBet.probability);
    const confidence = pct(bestBet.confidence);
    const v = valueNumber(bestBet.value);
    const status = String(bestBet.status || bestBet.grade || "").toUpperCase();
    const strong = status.includes("STRONG") || (v >= 10 && confidence >= 50);
    return { selection, probability, confidence, value: v, strong };
  }, [bestBet]);

  const likelyScore = result?.most_likely_scores?.[0];
  const cornersAvailable = Boolean(corners?.available);
  const cornersQuality = pct(corners?.quality?.total ?? corners?.quality ?? corners?.confidence ?? 0);
  const cardsAvailable = Boolean(cards?.available);
  const cardsQuality = pct(cards?.quality ?? 0);
  const referee = cards?.referee || {};

  const modelRecommendation = strongestMarket
    ? `Обнаружена ${strongestMarket.strong ? "высокая" : "положительная"} ценность в ставке ${strongestMarket.selection}`
    : "Сейчас модель не видит ставки с достаточным Value и Confidence";

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="brand-block">
          <LogoMark />
          <div>
            <div className="brand-name">Footballistika</div>
            <div className="brand-tagline">DATA · VALUE · FOOTBALL</div>
          </div>
        </div>

        <nav className="main-nav">
          <button type="button" className={activePage === "home" ? "active" : ""} onClick={() => setActivePage("home")}><Home size={17} />Главная</button>
          <button type="button" className={activePage === "statistics" ? "active" : ""} onClick={() => setActivePage("statistics")}><BarChart3 size={17} />Статистика</button>
          <button type="button" className={activePage === "about" ? "active" : ""} onClick={() => setActivePage("about")}><Info size={17} />О проекте</button>
        </nav>

        <div className="header-badge">
          <Zap size={17} />
          <div><strong>Footballistika Engine</strong><span>AI + реальные данные</span></div>
        </div>
      </header>

      <main id="top" className={`page-wrap ${activePage !== "home" ? "page-hidden" : ""}`}>
        <section className="hero-panel">
          <div className="hero-copy">
            <span className="hero-kicker"><Sparkles size={16} /> FOOTBALLISTIKA AI ANALYTICS</span>
            <h1><span>Footballistika.</span> Матч в цифрах</h1>
            <p>Форма, REAL xG, вероятности, коэффициенты, Value, угловые и карточки — в одном анализе матча.</p>
            <div className="hero-features">
              <div><div className="feature-icon green"><BarChart3 size={23} /></div><span><strong>Реальные данные</strong><small>xG, форма, угловые, коэффициенты</small></span></div>
              <div><div className="feature-icon yellow"><Zap size={23} /></div><span><strong>AI анализ</strong><small>Вероятность, Value и Confidence</small></span></div>
              <div><div className="feature-icon mint"><Shield size={23} /></div><span><strong>Без фантазий</strong><small>Только то, что подтверждено данными</small></span></div>
            </div>
          </div>
          <div className="hero-visual">
            <div className="hero-ball">⚽</div>
            <div className="hero-brush">READ THE GAME<br /><strong>THROUGH DATA</strong></div>
          </div>
        </section>

        <section id="analysis" className="search-panel">
          <div className="search-head">
            <div><span className="eyebrow">АНАЛИЗ МАТЧА</span><h2>Выберите команды</h2></div>
            <div className="engine-pill"><span className="live-dot" /> {result?.version || "ENGINE ONLINE"}</div>
          </div>
          <div className="selector-row">
            <label className="team-field"><span>Хозяева</span><input placeholder="Введите команду хозяев" value={homeTeam} onChange={(e) => setHomeTeam(e.target.value)} onKeyDown={onEnter} /></label>
            <div className="selector-vs">VS</div>
            <label className="team-field"><span>Гости</span><input placeholder="Введите команду гостей" value={awayTeam} onChange={(e) => setAwayTeam(e.target.value)} onKeyDown={onEnter} /></label>
            <button className="analyze-btn" onClick={analyzeMatch} disabled={loading || !homeTeam.trim() || !awayTeam.trim()}>
              {loading ? <><Loader2 className="spin" size={19} /> Анализируем...</> : <><Brain size={19} /> Анализировать <ChevronRight size={18} /></>}
            </button>
          </div>
          {error ? <div className="error-banner"><Shield size={18} /><span>{error}</span></div> : null}
        </section>

        {loading ? (
          <section className="loading-card premium-loader">
            <div className="loader-visual">
              <div className="loader-orbit"><Loader2 className="spin" size={42} /></div>
              <div className="loader-pulse-ring" />
            </div>
            <div className="loader-copy">
              <span className="loader-kicker">LIVE AI ANALYSIS</span>
              <h2>Собираем лучший сигнал для матча</h2>
              <p>{ANALYSIS_STAGES[loadingStage].label}</p>
              <div className="analysis-progress-track"><span style={{ width: `${((loadingStage + 1) / ANALYSIS_STAGES.length) * 100}%` }} /></div>
              <div className="analysis-steps">
                {ANALYSIS_STAGES.map((stage, index) => (
                  <div key={stage.label} className={`analysis-step ${index < loadingStage ? "done" : ""} ${index === loadingStage ? "active" : ""}`}>
                    <span>{index < loadingStage ? "✓" : stage.icon}</span>
                    <small>{stage.label}</small>
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        {!result && !loading ? (
          <section className="welcome-card">
            <div className="welcome-icon"><Bot size={34} /></div>
            <h2>Готов к анализу</h2>
            <p>Введите две команды и получите полный разбор матча в одном экране.</p>
          </section>
        ) : null}

        {result && !loading ? (
          <div className="results-stack" ref={resultsRef}>
            <section className="match-overview">
              <div className="league-line premium-league-line">
                <LeagueBadge src={result?.match?.league_emblem} name={result?.match?.league} code={result?.match?.league_code} />
                <div className="kickoff-chip"><Clock3 size={14} /> {result?.match?.kickoff_kyiv || result?.match?.kickoff_utc || "Время матча"}</div>
              </div>
              <div className="teams-row premium-teams-row">
                <div className="team-side">
                  <TeamCrest src={result?.match?.home_crest} name={result?.match?.home_team} side="home" />
                  <div><strong>{result?.match?.home_team}</strong><span>{result?.match?.home_tla || "HOME"} · Хозяева</span></div>
                </div>
                <div className="match-center">
                  <div className="big-vs">VS</div>
                  <small>AI MATCH CENTER</small>
                </div>
                <div className="team-side away-side">
                  <TeamCrest src={result?.match?.away_crest} name={result?.match?.away_team} side="away" />
                  <div><strong>{result?.match?.away_team}</strong><span>{result?.match?.away_tla || "AWAY"} · Гости</span></div>
                </div>
              </div>
              <div className="ai-recommendation">
                <div className="ai-icon"><Bot size={25} /></div>
                <div><span>AI РЕКОМЕНДАЦИЯ</span><strong>{modelRecommendation}</strong></div>
                {strongestMarket ? <span className={`recommendation-chip ${strongestMarket.strong ? "strong" : "value"}`}>{strongestMarket.strong ? "СИЛЬНАЯ СТАВКА" : "ВАЛУЙНАЯ СТАВКА"}</span> : <span className="recommendation-chip neutral">НЕТ СТАВКИ</span>}
              </div>
            </section>

            <div className="analysis-tabs">
              <span className="active"><BarChart3 size={17} />Общий анализ</span>
              <span><CircleDollarSign size={17} />Коэффициенты</span>
              <span><Database size={17} />Статистика</span>
              <span><Flag size={17} />Угловые</span>
              <span><Shield size={17} />Карточки</span>
              <span><Swords size={17} />H2H</span>
              <span><TrendingUp size={17} />Форма команд</span>
            </div>

            {bestBet ? (
              <section id="value" className={`hero-bet-card day-bet-card ${strongestMarket?.strong ? "strong" : "value"}`}>
                <div className="day-bet-head">
                  <div className="day-bet-trophy"><Trophy size={34} /></div>
                  <div className="day-bet-title">
                    <h2>СТАВКА ДНЯ</h2>
                    <span>ЛУЧШАЯ ВОЗМОЖНОСТЬ СЕГОДНЯ</span>
                  </div>
                  <div className="top-value-pill">👑 TOP VALUE</div>
                </div>

                <div className="day-bet-body">
                  <div className="day-bet-pick">
                    <span className="day-bet-kicker">НАША РЕКОМЕНДАЦИЯ</span>
                    <strong className="day-bet-selection">{prettyBetLabel(bestBet)}</strong>
                    <span className="day-bet-description">{prettyBetDescription(bestBet)}</span>
                    <div className="day-bet-badges">
                      <OddsStatus bet={bestBet} />
                      <span className="high-value-badge"><TrendingUp size={16} /> ВЫСОКИЙ VALUE</span>
                    </div>
                  </div>

                  <div className="day-bet-stats">
                    <div className="day-stat-card probability">
                      <span>Вероятность</span>
                      <strong>{percentText(bestBet.probability)}</strong>
                      <Progress value={bestBet.probability} tone="green" />
                    </div>
                    <div className="day-stat-card">
                      <span>Коэффициент</span>
                      <strong>{bestBet.odds ?? "—"}</strong>
                      <small>лучший доступный</small>
                    </div>
                    <div className="day-stat-card value-card">
                      <span>Value</span>
                      <strong>{valuePercent(bestBet.value)}</strong>
                      <small>преимущество модели</small>
                    </div>
                    <button className="day-bet-cta" type="button" onClick={() => document.getElementById("statistics")?.scrollIntoView({ behavior: "smooth" })}>
                      <TrendingUp size={24} />
                      ПОДРОБНЫЙ АНАЛИЗ
                      <ChevronRight size={24} />
                    </button>
                  </div>
                </div>

                <div className="day-bet-note">
                  <Sparkles size={18} />
                  <span>Модель показывает высокую вероятность прохода при положительном Value <strong>{valuePercent(bestBet.value)}</strong> и Confidence <strong>{percentText(bestBet.confidence)}</strong>.</span>
                </div>
              </section>
            ) : (
              <section className="hero-bet-card no-value"><div className="bet-ribbon"><Trophy size={19} /> ГЛАВНАЯ СТАВКА</div><div className="no-value-copy"><h2>Сейчас явной Value-ставки нет</h2><p>Это тоже полезный результат: модель не предлагает ставку ради ставки.</p></div></section>
            )}

            <div id="statistics" className="dashboard-grid">
              <section className="dashboard-main">
                <div className="panel-card">
                  <SectionTitle icon={<Layers3 size={20} />} title="Все варианты ставок" subtitle="Сравнение вероятности, коэффициента и Value" badge={`${markets.length} рынков`} />
                  <div className="value-table-wrap">
                    <table className="value-table">
                      <thead><tr><th>Ставка</th><th>Вероятность</th><th>Лучший кэф</th><th>Value</th><th>Confidence</th><th>Статус</th></tr></thead>
                      <tbody>
                        {(markets.length ? markets : bestBet ? [bestBet] : []).map((bet, index) => (
                          <tr key={`${bet.market}-${bet.selection}-${index}`} className={index === 0 ? "top-market" : ""}>
                            <td>
  <strong>{prettyBetLabel(bet)}</strong>
  <small>{prettyBetDescription(bet)}</small>
</td>
                            <td>{percentText(bet.probability)}</td>
                            <td><strong>{bet.odds ?? bet.coefficient ?? bet.price ?? "—"}</strong></td>
                            <td className={valueNumber(bet.value) > 0 ? "positive" : "negative"}>{valuePercent(bet.value)}</td>
                            <td><div className="confidence-cell"><span>{percentText(bet.confidence)}</span><Progress value={bet.confidence} tone="green" /></div></td>
                            <td><OddsStatus bet={bet} /></td>
                          </tr>
                        ))}
                        {!markets.length && !bestBet ? <tr><td colSpan="6" className="empty-table">Нет рынков, прошедших фильтр Value/Confidence.</td></tr> : null}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="panel-card">
                  <SectionTitle icon={<TrendingUp size={20} />} title="Форма и сила команд" subtitle="Последние матчи + домашняя/выездная форма" />
                  <div className="form-columns">
                    <div className="form-box"><div className="form-name"><strong>{result.match.home_team}</strong><span>Последние матчи</span></div><div className="form-pills">{(result?.form?.home || []).map((x, i) => <FormPill result={x} key={i} />)}</div><div className="mini-stat-row"><span>Home PPG</span><strong>{number(result?.form?.home_home?.points_per_game)}</strong></div><div className="mini-stat-row"><span>Забивает</span><strong>{number(result?.attack?.home)}</strong></div><div className="mini-stat-row"><span>Пропускает</span><strong>{number(result?.defense?.home)}</strong></div></div>
                    <div className="form-box"><div className="form-name"><strong>{result.match.away_team}</strong><span>Последние матчи</span></div><div className="form-pills">{(result?.form?.away || []).map((x, i) => <FormPill result={x} key={i} />)}</div><div className="mini-stat-row"><span>Away PPG</span><strong>{number(result?.form?.away_away?.points_per_game)}</strong></div><div className="mini-stat-row"><span>Забивает</span><strong>{number(result?.attack?.away)}</strong></div><div className="mini-stat-row"><span>Пропускает</span><strong>{number(result?.defense?.away)}</strong></div></div>
                  </div>
                </div>

                <div className="two-panels">
                  <div className="panel-card compact-panel"><SectionTitle icon={<Goal size={20} />} title="Голы" subtitle="Вероятности тоталов" /><div className="metric-list"><div><span>Over 1.5</span><strong>{percentText(goals.over_1_5)}</strong></div><div><span>Over 2.5</span><strong className="positive">{percentText(goals.over_2_5)}</strong></div><div><span>Under 2.5</span><strong>{percentText(goals.under_2_5)}</strong></div><div><span>Over 3.5</span><strong>{percentText(goals.over_3_5)}</strong></div></div></div>
                  <div className="panel-card compact-panel"><SectionTitle icon={<Swords size={20} />} title="Обе забьют / H2H" subtitle="Дополнительные сигналы" /><div className="metric-list"><div><span>ОЗ — Да</span><strong className="positive">{percentText(btts.yes)}</strong></div><div><span>ОЗ — Нет</span><strong>{percentText(btts.no)}</strong></div><div><span>H2H матчей</span><strong>{result?.h2h?.matches ?? 0}</strong></div><div><span>Топ счёт</span><strong>{likelyScore ? `${likelyScore.home}:${likelyScore.away}` : "—"}</strong></div></div></div>
                </div>

                <div className="panel-card"><SectionTitle icon={<CircleDollarSign size={20} />} title="Лучшие реальные коэффициенты" subtitle={`${result?.bookmakers_count ?? 0} букмекеров в событии`} badge="THE ODDS API" /><div className="odds-grid">{[["П1", odds["1"]],["X", odds.X],["П2", odds["2"]],["1X", odds["1X"]],["X2", odds.X2],["ТБ 2.5", odds.over_2_5],["ТМ 2.5", odds.under_2_5],["ОЗ Да", odds.btts_yes],["ОЗ Нет", odds.btts_no]].map(([label, val]) => <div className="odds-box" key={label}><span>{label}</span><strong>{val ?? "—"}</strong></div>)}</div></div>
              </section>

              <aside className="dashboard-side">
                <div className="side-card outcome-card"><SectionTitle icon={<Target size={20} />} title="Вероятности исхода" /><div className="outcome-row"><div><span>П1</span><strong>{percentText(prediction.home)}</strong><Progress value={prediction.home} tone="green" /></div><div><span>X</span><strong>{percentText(prediction.draw)}</strong><Progress value={prediction.draw} tone="blue" /></div><div><span>П2</span><strong>{percentText(prediction.away)}</strong><Progress value={prediction.away} tone="red" /></div></div><div className="double-chance"><span>1X <strong>{percentText(prediction.double_home)}</strong></span><span>X2 <strong>{percentText(prediction.double_away)}</strong></span></div></div>

                <div className="side-card"><SectionTitle icon={<BarChart3 size={20} />} title="Ожидаемые голы (xG)" /><div className="xg-versus"><div><span>{result.match.home_team}</span><strong>{number(xg.home, 3)}</strong><Progress value={Math.min(100, pct(xg.home) * 28)} tone="yellow" /></div><div className="xg-divider" /><div><span>{result.match.away_team}</span><strong>{number(xg.away, 3)}</strong><Progress value={Math.min(100, pct(xg.away) * 28)} tone="green" /></div></div><div className="mini-stat-row"><span>Base xG</span><strong>{number(xg.base_home, 3)} / {number(xg.base_away, 3)}</strong></div><div className="mini-stat-row"><span>REAL xG sample</span><strong>{xg?.real?.home_sample ?? "—"} / {xg?.real?.away_sample ?? "—"}</strong></div><div className="mini-stat-row"><span>История</span><strong>{result?.history?.home_matches ?? 0} / {result?.history?.away_matches ?? 0}</strong></div></div>

                <div className="side-card"><SectionTitle icon={<Flag size={20} />} title="Анализ угловых" badge={cornersAvailable ? "LIVE" : "N/A"} />{cornersAvailable ? <><div className="corner-versus"><div><span>{result.match.home_team}</span><strong>{number(corners.home, 2)}</strong></div><div><span>{result.match.away_team}</span><strong>{number(corners.away, 2)}</strong></div></div><div className="corner-total-box"><span>Ожидаемый тотал</span><strong>{number(corners.total, 2)}</strong></div>{cornersQuality ? <div className="quality-block"><div className="quality-ring" style={{ "--quality": `${Math.min(100, cornersQuality) * 3.6}deg` }}><span>{Math.round(cornersQuality)}%</span></div><div><strong>Качество прогноза</strong><span>Стабильность модели угловых</span></div></div> : null}</> : <div className="empty-side">{corners?.message || "Данные угловых недоступны."}</div>}</div>
                <div className="side-card cards-side">
                  <SectionTitle
                    icon={<Shield size={20} />}
                    title="Жёлтые карточки"
                    badge={cardsAvailable ? `${Math.min(cards?.home?.sample || 0, cards?.away?.sample || 0)}/30` : "N/A"}
                  />
                  {cardsAvailable ? (
                    <>
                      <div className="cards-versus">
                        <div>
                          <span>{result.match.home_team}</span>
                          <strong>{number(cards?.home?.average, 2)}</strong>
                          <small>среднее за {cards?.home?.sample || 0} матчей</small>
                        </div>
                        <div>
                          <span>{result.match.away_team}</span>
                          <strong>{number(cards?.away?.average, 2)}</strong>
                          <small>среднее за {cards?.away?.sample || 0} матчей</small>
                        </div>
                      </div>

                      <div className="cards-total-box">
                        <div>
                          <span>Средний тотал команд</span>
                          <strong>{number(cards?.team_total_average, 2)}</strong>
                        </div>
                        <div>
                          <span>Ожидаемый тотал</span>
                          <strong>{number(cards?.expected_total, 2)}</strong>
                        </div>
                      </div>

                      <div className="referee-card">
                        <div className="referee-icon">🧑‍⚖️</div>
                        <div className="referee-copy">
                          <span>Арбитр матча</span>
                          <strong>{referee?.name || "Пока не назначен"}</strong>
                          {referee?.assigned ? (
                            <small>
                              {referee?.yellow_average != null
                                ? `${number(referee.yellow_average, 2)} жёлтых за матч`
                                : "Среднее по карточкам недоступно"}
                              {referee?.matches ? ` · ${referee.matches} матчей` : ""}
                            </small>
                          ) : (
                            <small>{referee?.message || "Данные арбитра пока не опубликованы"}</small>
                          )}
                        </div>
                      </div>

                      {cardsQuality ? (
                        <div className="cards-quality-row">
                          <span>Качество данных</span>
                          <Progress value={cardsQuality} tone="yellow" />
                          <strong>{Math.round(cardsQuality)}%</strong>
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="empty-side">{cards?.message || "Данные по жёлтым карточкам недоступны."}</div>
                  )}
                </div>

                <div className="side-card ai-side"><SectionTitle icon={<Brain size={20} />} title="AI Assessment" /><div className="ai-score-row"><div><span>Rating</span><strong>{ai.rating ?? "—"}</strong></div><div><span>Risk</span><strong>{ai.risk ?? "—"}</strong></div></div><p>{ai.summary || modelRecommendation}</p></div>
              </aside>
            </div>

            {bestBet ? (
              <div className="mobile-value-dock">
                <div><span>TOP VALUE</span><strong>{bestBet.selection || bestBet.market}</strong></div>
                <div><span>Value</span><strong>{valuePercent(bestBet.value)}</strong></div>
                <div><span>Кэф</span><strong>{bestBet.odds ?? "—"}</strong></div>
              </div>
            ) : null}

            <section id="about" className="trust-strip">
              <div><div className="trust-icon green"><BarChart3 size={22} /></div><span><strong>Реальные коэффициенты</strong><small>Сравнение доступных букмекеров</small></span></div>
              <div><div className="trust-icon blue"><Database size={22} /></div><span><strong>Глубокий анализ</strong><small>xG, форма, H2H и Poisson</small></span></div>
              <div><div className="trust-icon purple"><Zap size={22} /></div><span><strong>Поиск Value</strong><small>Вероятность против рыночной цены</small></span></div>
              <div><div className="trust-icon orange"><Shield size={22} /></div><span><strong>Без фейковых данных</strong><small>Нет данных — так и показываем</small></span></div>
            </section>

            <footer className="site-footer"><div className="footer-brand"><LogoMark /><strong>Footballistika</strong></div><span>Футбол — это больше, чем игра. Это данные. Это возможности.</span><span>{result?.version || "Football AI Analyst"}</span></footer>
          </div>
        ) : null}
      </main>
      {activePage === "statistics" ? <StatisticsPage /> : null}
      {activePage === "about" ? <AboutPage /> : null}
    </div>
  );
}

export default App;

