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
  { label: "Р—Р°РіСЂСѓР¶Р°РµРј С„РѕСЂРјСѓ РєРѕРјР°РЅРґ", icon: "01" },
  { label: "РЎС‡РёС‚Р°РµРј REAL xG", icon: "02" },
  { label: "РЎРІРµСЂСЏРµРј СЂРµР°Р»СЊРЅС‹Рµ РєРѕСЌС„С„РёС†РёРµРЅС‚С‹", icon: "03" },
  { label: "РС‰РµРј Value Рё Confidence", icon: "04" },
  { label: "РџСЂРѕРІРµСЂСЏРµРј СѓРіР»РѕРІС‹Рµ", icon: "05" },
  { label: "РђРЅР°Р»РёР·РёСЂСѓРµРј Р¶С‘Р»С‚С‹Рµ РєР°СЂС‚РѕС‡РєРё Рё Р°СЂР±РёС‚СЂР°", icon: "06" },
];

const teamInitials = (name = "") => {
  const words = String(name).trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "FC";
  const ignored = new Set(["fc", "cf", "afc", "sc", "club", "de", "calcio", "balompiГ©"]);
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
  return Number.isFinite(n) ? n.toFixed(digits) : "вЂ”";
};

const percentText = (value) => `${pct(value).toFixed(1)}%`;

const valuePercent = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "вЂ”";
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
      .replace(/С‘/g, "Рµ")
      .replace(/[вЂ“вЂ”]/g, "-")
      .replace(/\s+/g, " ");

  const candidates = [selection, market].filter(Boolean);

  const exactMap = {
    "over_25": "РўР‘ 2.5",
    "over25": "РўР‘ 2.5",
    "o2.5": "РўР‘ 2.5",
    "С‚Р± 2.5": "РўР‘ 2.5",
    "С‚Р±2.5": "РўР‘ 2.5",
    "С‚РѕС‚Р°Р» Р±РѕР»СЊС€Рµ 2.5": "РўР‘ 2.5",
    "Р±РѕР»СЊС€Рµ 2.5": "РўР‘ 2.5",

    "under_25": "РўРњ 2.5",
    "under25": "РўРњ 2.5",
    "u2.5": "РўРњ 2.5",
    "С‚Рј 2.5": "РўРњ 2.5",
    "С‚Рј2.5": "РўРњ 2.5",
    "С‚РѕС‚Р°Р» РјРµРЅСЊС€Рµ 2.5": "РўРњ 2.5",
    "РјРµРЅСЊС€Рµ 2.5": "РўРњ 2.5",

    "home_win": "Рџ1",
    "home": "Рџ1",
    "Рї1": "Рџ1",
    "РїРѕР±РµРґР° С…РѕР·СЏРµРІ": "Рџ1",

    "draw": "РҐ",
    "x": "РҐ",
    "С…": "РҐ",
    "РЅРёС‡СЊСЏ": "РҐ",

    "away_win": "Рџ2",
    "away": "Рџ2",
    "Рї2": "Рџ2",
    "РїРѕР±РµРґР° РіРѕСЃС‚РµР№": "Рџ2",

    "double_home": "1РҐ",
    "1x": "1РҐ",
    "1С…": "1РҐ",
    "С…РѕР·СЏРµРІР° РЅРµ РїСЂРѕРёРіСЂР°СЋС‚": "1РҐ",

    "double_away": "РҐ2",
    "x2": "РҐ2",
    "С…2": "РҐ2",
    "РіРѕСЃС‚Рё РЅРµ РїСЂРѕРёРіСЂР°СЋС‚": "РҐ2",

    "btts_yes": "РћР— вЂ” Р”Р°",
    "btts yes": "РћР— вЂ” Р”Р°",
    "РѕР· РґР°": "РћР— вЂ” Р”Р°",
    "РѕР· - РґР°": "РћР— вЂ” Р”Р°",
    "РѕР±Рµ Р·Р°Р±СЊСЋС‚ РґР°": "РћР— вЂ” Р”Р°",

    "btts_no": "РћР— вЂ” РќРµС‚",
    "btts no": "РћР— вЂ” РќРµС‚",
    "РѕР· РЅРµС‚": "РћР— вЂ” РќРµС‚",
    "РѕР· - РЅРµС‚": "РћР— вЂ” РќРµС‚",
    "РѕР±Рµ Р·Р°Р±СЊСЋС‚ РЅРµС‚": "РћР— вЂ” РќРµС‚",
  };

  for (const candidate of candidates) {
    const normalized = normalize(candidate);
    const key = normalized.replace(/\s+/g, "_");
    if (exactMap[normalized]) return exactMap[normalized];
    if (exactMap[key]) return exactMap[key];

    // Totals with arbitrary line.
    const overMatch =
      normalized.match(/(?:over|Р±РѕР»СЊС€Рµ|С‚Р±)\s*([0-9]+(?:[.,][0-9]+)?)/i) ||
      normalized.match(/([0-9]+(?:[.,][0-9]+)?)\s*(?:over|Р±РѕР»СЊС€Рµ)/i);
    if (overMatch && !normalized.includes("corner") && !normalized.includes("СѓРіР»РѕРІ")) {
      return `РўР‘ ${overMatch[1].replace(",", ".")}`;
    }

    const underMatch =
      normalized.match(/(?:under|РјРµРЅСЊС€Рµ|С‚Рј)\s*([0-9]+(?:[.,][0-9]+)?)/i) ||
      normalized.match(/([0-9]+(?:[.,][0-9]+)?)\s*(?:under|РјРµРЅСЊС€Рµ)/i);
    if (underMatch && !normalized.includes("corner") && !normalized.includes("СѓРіР»РѕРІ")) {
      return `РўРњ ${underMatch[1].replace(",", ".")}`;
    }

    // Corners.
    if (normalized.includes("corner") || normalized.includes("СѓРіР»РѕРІ")) {
      const line = normalized.match(/[0-9]+(?:[.,][0-9]+)?/);
      const lineText = line ? line[0].replace(",", ".") : "";
      if (normalized.includes("under") || normalized.includes("РјРµРЅСЊС€Рµ") || normalized.includes("С‚Рј")) {
        return `РўРњ ${lineText} СѓРіР»РѕРІС‹С…`.trim();
      }
      if (normalized.includes("over") || normalized.includes("Р±РѕР»СЊС€Рµ") || normalized.includes("С‚Р±")) {
        return `РўР‘ ${lineText} СѓРіР»РѕРІС‹С…`.trim();
      }
      return lineText ? `РўРѕС‚Р°Р» ${lineText} СѓРіР»РѕРІС‹С…` : "РЈРіР»РѕРІС‹Рµ";
    }
  }

  // If backend already returned a readable Russian label, keep it.
  if (selection && /[Рђ-РЇР°-СЏРЃС‘]/.test(selection)) return selection;
  if (market && /[Рђ-РЇР°-СЏРЃС‘]/.test(market)) return market;

  return "вЂ”";
};

const prettyBetDescription = (bet) => {
  const label = prettyBetLabel(bet);
  if (label === "РўР‘ 2.5") return "Р‘РѕР»СЊС€Рµ 2.5 РіРѕР»РѕРІ РІ РјР°С‚С‡Рµ";
  if (label === "РўРњ 2.5") return "РњРµРЅСЊС€Рµ 2.5 РіРѕР»РѕРІ РІ РјР°С‚С‡Рµ";
  if (label === "Рџ1") return "РџРѕР±РµРґР° С…РѕР·СЏРµРІ";
  if (label === "Рџ2") return "РџРѕР±РµРґР° РіРѕСЃС‚РµР№";
  if (label === "РҐ" || label === "X") return "РќРёС‡СЊСЏ";
  if (label === "1РҐ" || label === "1X") return "РҐРѕР·СЏРµРІР° РЅРµ РїСЂРѕРёРіСЂР°СЋС‚";
  if (label === "РҐ2" || label === "X2") return "Р“РѕСЃС‚Рё РЅРµ РїСЂРѕРёРіСЂР°СЋС‚";
  if (label === "РћР— вЂ” Р”Р°") return "РћР±Рµ РєРѕРјР°РЅРґС‹ Р·Р°Р±СЊСЋС‚";
  if (label === "РћР— вЂ” РќРµС‚") return "РҐРѕС‚СЏ Р±С‹ РѕРґРЅР° РєРѕРјР°РЅРґР° РЅРµ Р·Р°Р±СЊС‘С‚";
  return "Р›СѓС‡С€Р°СЏ СЃС‚Р°РІРєР° РїРѕ РѕС†РµРЅРєРµ РјРѕРґРµР»Рё";
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
      <div className="logo-ball">вљЅ</div>
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
  const value = String(result || "вЂ”").toUpperCase();
  const cls = value === "W" ? "win" : value === "L" ? "loss" : value === "D" ? "draw" : "";
  return <span className={`form-pill ${cls}`}>{value}</span>;
}

function OddsStatus({ bet }) {
  const label = String(bet?.status || bet?.grade || bet?.recommendation || "").toUpperCase();
  if (label.includes("STRONG")) return <span className="status-badge strong">рџ”Ґ РЎРР›Р¬РќРђРЇ РЎРўРђР’РљРђ</span>;
  if (label.includes("VALUE")) return <span className="status-badge value">рџ’Ћ Р’РђР›РЈР™РќРђРЇ РЎРўРђР’РљРђ</span>;
  if (valueNumber(bet?.value) >= 10 && pct(bet?.confidence) >= 50) {
    return <span className="status-badge strong">рџ”Ґ РЎРР›Р¬РќРђРЇ РЎРўРђР’РљРђ</span>;
  }
  if (valueNumber(bet?.value) >= 3) return <span className="status-badge value">рџ’Ћ Р’РђР›РЈР™РќРђРЇ РЎРўРђР’РљРђ</span>;
  return <span className="status-badge neutral">РќР•Рў РЎРўРђР’РљР</span>;
}


const monthNow = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

const statusMeta = (status) => {
  if (status === "win") return { label: "Р’Р«РР“Р Р«РЁ", cls: "win" };
  if (status === "loss") return { label: "РџР РћРР“Р Р«РЁ", cls: "loss" };
  if (status === "void") return { label: "Р’РћР—Р’Р РђРў", cls: "void" };
  if (status === "no_bet") return { label: "РќР•Рў РЎРўРђР’РљР", cls: "neutral" };
  return { label: "РћР–РР”РђР•Рў", cls: "pending" };
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
      setStatsError(err?.message || "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ СЃС‚Р°С‚РёСЃС‚РёРєСѓ.");
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
          <h1>РЎС‚Р°С‚РёСЃС‚РёРєР° <span>СЃС‚Р°РІРѕРє РґРЅСЏ</span></h1>
          <p>РљР°Р¶РґР°СЏ СЃС‚Р°РІРєР° РґРЅСЏ С„РёРєСЃРёСЂСѓРµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё. РџРѕСЃР»Рµ С„РёРЅР°Р»СЊРЅРѕРіРѕ СЃРІРёСЃС‚РєР° СЃРёСЃС‚РµРјР° РїСЂРѕРІРµСЂСЏРµС‚ СЃС‡С‘С‚ Рё РїРµСЂРµСЃС‡РёС‚С‹РІР°РµС‚ РјРµСЃСЏС‡РЅС‹Р№ РїСЂРѕС„РёС‚.</p>
        </div>
        <div className="stats-month-control">
          <label htmlFor="stats-month">РњРµСЃСЏС†</label>
          <input id="stats-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          <button type="button" onClick={() => loadStats(month)} disabled={loadingStats}>
            {loadingStats ? <Loader2 className="spin" size={17} /> : <BarChart3 size={17} />} РћР±РЅРѕРІРёС‚СЊ
          </button>
        </div>
      </section>

      {statsError ? (
        <div className="error-banner">
          {statsError}
          <button type="button" onClick={() => loadStats(month)} style={{ marginLeft: 12 }}>
            РџРѕРІС‚РѕСЂРёС‚СЊ
          </button>
        </div>
      ) : null}

      <section className="stats-summary-grid">
        <div className={`stats-kpi profit ${profit >= 0 ? "positive" : "negative"}`}>
          <span>РџСЂРѕС„РёС‚ Р·Р° РјРµСЃСЏС†</span>
          <strong>{profit >= 0 ? "+" : ""}{profit.toFixed(2)} u</strong>
          <small>РїСЂРё С„РёРєСЃРёСЂРѕРІР°РЅРЅРѕР№ СЃС‚Р°РІРєРµ 1 unit</small>
        </div>
        <div className="stats-kpi"><span>ROI</span><strong>{Number(summary.roi_percent || 0).toFixed(1)}%</strong><small>РїСЂРёР±С‹Р»СЊ / СЃСѓРјРјР° СЃС‚Р°РІРѕРє</small></div>
        <div className="stats-kpi"><span>Р’С‹РёРіСЂС‹С€Рё</span><strong>{summary.wins || 0}</strong><small>РёР· {summary.bets_settled || 0} СЂР°СЃСЃС‡РёС‚Р°РЅРЅС‹С…</small></div>
        <div className="stats-kpi"><span>Win rate</span><strong>{Number(summary.win_rate || 0).toFixed(1)}%</strong><small>{summary.losses || 0} РїСЂРѕРёРіСЂС‹С€РµР№</small></div>
        <div className="stats-kpi"><span>РћР¶РёРґР°СЋС‚</span><strong>{summary.pending || 0}</strong><small>РјР°С‚С‡Рё РµС‰С‘ РЅРµ СЂР°СЃСЃС‡РёС‚Р°РЅС‹</small></div>
        <div className="stats-kpi"><span>РџСЂРѕР°РЅР°Р»РёР·РёСЂРѕРІР°РЅРѕ</span><strong>{summary.matches_analyzed || 0}</strong><small>РјР°С‚С‡РµР№ Р·Р° РІС‹Р±СЂР°РЅРЅС‹Р№ РјРµСЃСЏС†</small></div>
      </section>

      <section className="panel-card stats-journal-card">
        <SectionTitle icon={<Database size={20} />} title="Р–СѓСЂРЅР°Р» СЃС‚Р°РІРѕРє РґРЅСЏ" subtitle="Р РµР·СѓР»СЊС‚Р°С‚ С„РёРєСЃРёСЂСѓРµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РїРѕ РёС‚РѕРіРѕРІРѕРјСѓ СЃС‡С‘С‚Сѓ" badge={`${bets.length} РјР°С‚С‡РµР№`} />
        <div className="value-table-wrap stats-table-wrap">
          <table className="value-table stats-table">
            <thead><tr><th>Р”Р°С‚Р°</th><th>РњР°С‚С‡</th><th>РЎС‚Р°РІРєР° РґРЅСЏ</th><th>РљСЌС„</th><th>Р РµР·СѓР»СЊС‚Р°С‚</th><th>РЎС‡С‘С‚</th><th>РџСЂРѕС„РёС‚</th></tr></thead>
            <tbody>
              {bets.map((bet) => {
                const meta = statusMeta(bet.status);
                const rawDate = bet.kickoff_utc || bet.kickoff || bet.match_date || bet.created_at || null;
                const date = rawDate ? new Date(rawDate) : null;
                const profitValue = Number(bet.profit || 0);
                return (
                  <tr key={bet.id}>
                    <td>{date ? date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) : "вЂ”"}<small>{date ? date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : ""}</small></td>
                    <td><strong>{bet.home_team} вЂ” {bet.away_team}</strong><small>{bet.league || ""}</small></td>
                    <td><strong>{prettyBetLabel(bet)}</strong><small>{prettyBetDescription(bet)}</small></td>
                    <td><strong>{bet.odds ?? bet.coefficient ?? bet.price ?? "вЂ”"}</strong></td>
                    <td><span className={`bet-result-badge ${meta.cls}`}>{meta.label}</span></td>
                    <td><strong>{bet.home_score != null && bet.away_score != null ? `${bet.home_score}:${bet.away_score}` : "вЂ”"}</strong></td>
                    <td className={profitValue > 0 ? "positive" : profitValue < 0 ? "negative" : ""}>{bet.status === "win" || bet.status === "loss" || bet.status === "void" ? `${profitValue > 0 ? "+" : ""}${profitValue.toFixed(2)} u` : "вЂ”"}</td>
                  </tr>
                );
              })}
              {!bets.length && !loadingStats ? <tr><td colSpan="7" className="empty-table">Р’ СЌС‚РѕРј РјРµСЃСЏС†Рµ РїРѕРєР° РЅРµС‚ Р·Р°С„РёРєСЃРёСЂРѕРІР°РЅРЅС‹С… СЃС‚Р°РІРѕРє РґРЅСЏ.</td></tr> : null}
              {loadingStats && !bets.length ? <tr><td colSpan="7" className="empty-table"><Loader2 className="spin inline-spinner" size={18} /> РџСЂРѕРІРµСЂСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹ РјР°С‚С‡РµР№...</td></tr> : null}
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
          <h1>Рћ <span>РїСЂРѕРµРєС‚Рµ</span></h1>
          <p>Footballistika РѕР±СЉРµРґРёРЅСЏРµС‚ С„РѕСЂРјСѓ РєРѕРјР°РЅРґ, REAL xG, Poisson-РјРѕРґРµР»СЊ, СЂРµР°Р»СЊРЅС‹Рµ Р±СѓРєРјРµРєРµСЂСЃРєРёРµ РєРѕСЌС„С„РёС†РёРµРЅС‚С‹, Value, Confidence Рё Р°РЅР°Р»РёР· СѓРіР»РѕРІС‹С… РІ РѕРґРЅРѕРј РїРѕРЅСЏС‚РЅРѕРј РёРЅС‚РµСЂС„РµР№СЃРµ.</p>
        </div>
      </section>
      <section className="about-grid">
        <div className="panel-card"><BarChart3 size={25} /><h3>Р РµР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ</h3><p>РСЃРїРѕР»СЊР·СѓРµРј РёСЃС‚РѕСЂРёСЋ РјР°С‚С‡РµР№, xG, С„РѕСЂРјСѓ, РґРѕРјР°С€РЅРёРµ/РІС‹РµР·РґРЅС‹Рµ РїРѕРєР°Р·Р°С‚РµР»Рё Рё РґРѕСЃС‚СѓРїРЅС‹Рµ РєРѕСЌС„С„РёС†РёРµРЅС‚С‹.</p></div>
        <div className="panel-card"><Target size={25} /><h3>Value РїСЂРµР¶РґРµ РІСЃРµРіРѕ</h3><p>РЎР°Р№С‚ РЅРµ РёС‰РµС‚ СЃС‚Р°РІРєСѓ СЂР°РґРё СЃС‚Р°РІРєРё. Р“Р»Р°РІРЅР°СЏ СЂРµРєРѕРјРµРЅРґР°С†РёСЏ РїРѕСЏРІР»СЏРµС‚СЃСЏ С‚РѕР»СЊРєРѕ С‚Р°Рј, РіРґРµ РјРѕРґРµР»СЊ РІРёРґРёС‚ С†РµРЅРЅРѕСЃС‚СЊ.</p></div>
        <div className="panel-card"><Database size={25} /><h3>РџСЂРѕРІРµСЂСЏРµРјС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚</h3><p>РЎС‚Р°РІРєРё РґРЅСЏ СЃРѕС…СЂР°РЅСЏСЋС‚СЃСЏ РІ Р¶СѓСЂРЅР°Р»Рµ. РџРѕСЃР»Рµ РјР°С‚С‡Р° СЂРµР·СѓР»СЊС‚Р°С‚ Рё РїСЂРѕС„РёС‚ СЂР°СЃСЃС‡РёС‚С‹РІР°СЋС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.</p></div>
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
      setError(err?.message || "РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ Р°РЅР°Р»РёР·. РџСЂРѕРІРµСЂСЊ backend РЅР° РїРѕСЂС‚Сѓ 8000.");
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
  // "РЎС‚Р°РІРєР° РґРЅСЏ" РґРѕР»Р¶РЅР° СЃС‚СЂРѕРіРѕ СЃРѕРІРїР°РґР°С‚СЊ СЃ С„РёРЅР°Р»СЊРЅРѕР№ СЃС‚Р°РІРєРѕР№ РјРѕРґРµР»Рё.
  // best_overall РІ backend РјРѕР¶РµС‚ СЃРѕРґРµСЂР¶Р°С‚СЊ СЃС‹СЂРѕР№ РѕР±СЉРµРєС‚ (РЅР°РїСЂРёРјРµСЂ, corner/football)
  // Рё РЅРµ СЏРІР»СЏРµС‚СЃСЏ РёСЃС‚РѕС‡РЅРёРєРѕРј РґР»СЏ РіР»Р°РІРЅРѕР№ С„СѓС‚Р±РѕР»СЊРЅРѕР№ СЂРµРєРѕРјРµРЅРґР°С†РёРё РЅР° UI.
  const bestBet = result?.best_bet || markets?.[0] || null;
  const ai = result?.ai_assessment || {};

  const strongestMarket = useMemo(() => {
    if (!bestBet) return null;
    const selection = bestBet.selection || bestBet.market || "Р“Р»Р°РІРЅР°СЏ СЃС‚Р°РІРєР°";
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
    ? `РћР±РЅР°СЂСѓР¶РµРЅР° ${strongestMarket.strong ? "РІС‹СЃРѕРєР°СЏ" : "РїРѕР»РѕР¶РёС‚РµР»СЊРЅР°СЏ"} С†РµРЅРЅРѕСЃС‚СЊ РІ СЃС‚Р°РІРєРµ ${strongestMarket.selection}`
    : "РЎРµР№С‡Р°СЃ РјРѕРґРµР»СЊ РЅРµ РІРёРґРёС‚ СЃС‚Р°РІРєРё СЃ РґРѕСЃС‚Р°С‚РѕС‡РЅС‹Рј Value Рё Confidence";

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="brand-block">
          <LogoMark />
          <div>
            <div className="brand-name">FootballAI</div>
            <div className="brand-tagline">DATA. VALUE. PROFIT.</div>
          </div>
        </div>

        <nav className="main-nav">
          <button type="button" className={activePage === "home" ? "active" : ""} onClick={() => setActivePage("home")}><Home size={17} />Р“Р»Р°РІРЅР°СЏ</button>
          <button type="button" className={activePage === "statistics" ? "active" : ""} onClick={() => setActivePage("statistics")}><BarChart3 size={17} />РЎС‚Р°С‚РёСЃС‚РёРєР°</button>
          <button type="button" className={activePage === "about" ? "active" : ""} onClick={() => setActivePage("about")}><Info size={17} />Рћ РїСЂРѕРµРєС‚Рµ</button>
        </nav>

        <div className="header-badge">
          <Zap size={17} />
          <div><strong>РџСЂРѕС„Рё-Р°РЅР°Р»РёС‚РёРєР°</strong><span>AI + СЂРµР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ</span></div>
        </div>
      </header>

      <main id="top" className={`page-wrap ${activePage !== "home" ? "page-hidden" : ""}`}>
        <section className="hero-panel">
          <div className="hero-copy">
            <span className="hero-kicker"><Sparkles size={16} /> FOOTBALL AI ANALYST</span>
            <h1><span>Р‘РѕР»СЊС€Рµ,</span> С‡РµРј РїСЂРѕСЃС‚Рѕ РїСЂРѕРіРЅРѕР·С‹</h1>
            <p>РђРЅР°Р»РёР·РёСЂСѓРµРј С„РѕСЂРјСѓ, xG, РєРѕСЌС„С„РёС†РёРµРЅС‚С‹ Рё СЂС‹РЅРѕРє. РќР°С…РѕРґРёРј С†РµРЅРЅРѕСЃС‚СЊ РґРѕ С‚РѕРіРѕ, РєР°Рє РѕРЅР° РёСЃС‡РµР·РЅРµС‚.</p>
            <div className="hero-features">
              <div><div className="feature-icon green"><BarChart3 size={23} /></div><span><strong>Р РµР°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ</strong><small>xG, С„РѕСЂРјР°, СѓРіР»РѕРІС‹Рµ, РєРѕСЌС„С„РёС†РёРµРЅС‚С‹</small></span></div>
              <div><div className="feature-icon yellow"><Zap size={23} /></div><span><strong>AI Р°РЅР°Р»РёР·</strong><small>Р’РµСЂРѕСЏС‚РЅРѕСЃС‚СЊ, Value Рё Confidence</small></span></div>
              <div><div className="feature-icon mint"><Shield size={23} /></div><span><strong>Р‘РµР· С„Р°РЅС‚Р°Р·РёР№</strong><small>РўРѕР»СЊРєРѕ С‚Рѕ, С‡С‚Рѕ РїРѕРґС‚РІРµСЂР¶РґРµРЅРѕ РґР°РЅРЅС‹РјРё</small></span></div>
            </div>
          </div>
          <div className="hero-visual">
            <div className="hero-ball">вљЅ</div>
            <div className="hero-brush">GOOD BETS<br /><strong>BETTER DAYS</strong></div>
          </div>
        </section>

        <section id="analysis" className="search-panel">
          <div className="search-head">
            <div><span className="eyebrow">РђРќРђР›РР— РњРђРўР§Рђ</span><h2>Р’С‹Р±РµСЂРёС‚Рµ РєРѕРјР°РЅРґС‹</h2></div>
            <div className="engine-pill"><span className="live-dot" /> {result?.version || "ENGINE ONLINE"}</div>
          </div>
          <div className="selector-row">
            <label className="team-field"><span>РҐРѕР·СЏРµРІР°</span><input placeholder="Р’РІРµРґРёС‚Рµ РєРѕРјР°РЅРґСѓ С…РѕР·СЏРµРІ" value={homeTeam} onChange={(e) => setHomeTeam(e.target.value)} onKeyDown={onEnter} /></label>
            <div className="selector-vs">VS</div>
            <label className="team-field"><span>Р“РѕСЃС‚Рё</span><input placeholder="Р’РІРµРґРёС‚Рµ РєРѕРјР°РЅРґСѓ РіРѕСЃС‚РµР№" value={awayTeam} onChange={(e) => setAwayTeam(e.target.value)} onKeyDown={onEnter} /></label>
            <button className="analyze-btn" onClick={analyzeMatch} disabled={loading || !homeTeam.trim() || !awayTeam.trim()}>
              {loading ? <><Loader2 className="spin" size={19} /> РђРЅР°Р»РёР·РёСЂСѓРµРј...</> : <><Brain size={19} /> РђРЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ <ChevronRight size={18} /></>}
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
              <h2>РЎРѕР±РёСЂР°РµРј Р»СѓС‡С€РёР№ СЃРёРіРЅР°Р» РґР»СЏ РјР°С‚С‡Р°</h2>
              <p>{ANALYSIS_STAGES[loadingStage].label}</p>
              <div className="analysis-progress-track"><span style={{ width: `${((loadingStage + 1) / ANALYSIS_STAGES.length) * 100}%` }} /></div>
              <div className="analysis-steps">
                {ANALYSIS_STAGES.map((stage, index) => (
                  <div key={stage.label} className={`analysis-step ${index < loadingStage ? "done" : ""} ${index === loadingStage ? "active" : ""}`}>
                    <span>{index < loadingStage ? "вњ“" : stage.icon}</span>
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
            <h2>Р“РѕС‚РѕРІ Рє Р°РЅР°Р»РёР·Сѓ</h2>
            <p>Р’РІРµРґРёС‚Рµ РґРІРµ РєРѕРјР°РЅРґС‹ Рё РїРѕР»СѓС‡РёС‚Рµ РїРѕР»РЅС‹Р№ СЂР°Р·Р±РѕСЂ РјР°С‚С‡Р° РІ РѕРґРЅРѕРј СЌРєСЂР°РЅРµ.</p>
          </section>
        ) : null}

        {result && !loading ? (
          <div className="results-stack" ref={resultsRef}>
            <section className="match-overview">
              <div className="league-line premium-league-line">
                <LeagueBadge src={result?.match?.league_emblem} name={result?.match?.league} code={result?.match?.league_code} />
                <div className="kickoff-chip"><Clock3 size={14} /> {result?.match?.kickoff_kyiv || result?.match?.kickoff_utc || "Р’СЂРµРјСЏ РјР°С‚С‡Р°"}</div>
              </div>
              <div className="teams-row premium-teams-row">
                <div className="team-side">
                  <TeamCrest src={result?.match?.home_crest} name={result?.match?.home_team} side="home" />
                  <div><strong>{result?.match?.home_team}</strong><span>{result?.match?.home_tla || "HOME"} В· РҐРѕР·СЏРµРІР°</span></div>
                </div>
                <div className="match-center">
                  <div className="big-vs">VS</div>
                  <small>AI MATCH CENTER</small>
                </div>
                <div className="team-side away-side">
                  <TeamCrest src={result?.match?.away_crest} name={result?.match?.away_team} side="away" />
                  <div><strong>{result?.match?.away_team}</strong><span>{result?.match?.away_tla || "AWAY"} В· Р“РѕСЃС‚Рё</span></div>
                </div>
              </div>
              <div className="ai-recommendation">
                <div className="ai-icon"><Bot size={25} /></div>
                <div><span>AI Р Р•РљРћРњР•РќР”РђР¦РРЇ</span><strong>{modelRecommendation}</strong></div>
                {strongestMarket ? <span className={`recommendation-chip ${strongestMarket.strong ? "strong" : "value"}`}>{strongestMarket.strong ? "РЎРР›Р¬РќРђРЇ РЎРўРђР’РљРђ" : "Р’РђР›РЈР™РќРђРЇ РЎРўРђР’РљРђ"}</span> : <span className="recommendation-chip neutral">РќР•Рў РЎРўРђР’РљР</span>}
              </div>
            </section>

            <div className="analysis-tabs">
              <span className="active"><BarChart3 size={17} />РћР±С‰РёР№ Р°РЅР°Р»РёР·</span>
              <span><CircleDollarSign size={17} />РљРѕСЌС„С„РёС†РёРµРЅС‚С‹</span>
              <span><Database size={17} />РЎС‚Р°С‚РёСЃС‚РёРєР°</span>
              <span><Flag size={17} />РЈРіР»РѕРІС‹Рµ</span>
              <span><Shield size={17} />РљР°СЂС‚РѕС‡РєРё</span>
              <span><Swords size={17} />H2H</span>
              <span><TrendingUp size={17} />Р¤РѕСЂРјР° РєРѕРјР°РЅРґ</span>
            </div>

            {bestBet ? (
              <section id="value" className={`hero-bet-card day-bet-card ${strongestMarket?.strong ? "strong" : "value"}`}>
                <div className="day-bet-head">
                  <div className="day-bet-trophy"><Trophy size={34} /></div>
                  <div className="day-bet-title">
                    <h2>РЎРўРђР’РљРђ Р”РќРЇ</h2>
                    <span>Р›РЈР§РЁРђРЇ Р’РћР—РњРћР–РќРћРЎРўР¬ РЎР•Р“РћР”РќРЇ</span>
                  </div>
                  <div className="top-value-pill">рџ‘‘ TOP VALUE</div>
                </div>

                <div className="day-bet-body">
                  <div className="day-bet-pick">
                    <span className="day-bet-kicker">РќРђРЁРђ Р Р•РљРћРњР•РќР”РђР¦РРЇ</span>
                    <strong className="day-bet-selection">{prettyBetLabel(bestBet)}</strong>
                    <span className="day-bet-description">{prettyBetDescription(bestBet)}</span>
                    <div className="day-bet-badges">
                      <OddsStatus bet={bestBet} />
                      <span className="high-value-badge"><TrendingUp size={16} /> Р’Р«РЎРћРљРР™ VALUE</span>
                    </div>
                  </div>

                  <div className="day-bet-stats">
                    <div className="day-stat-card probability">
                      <span>Р’РµСЂРѕСЏС‚РЅРѕСЃС‚СЊ</span>
                      <strong>{percentText(bestBet.probability)}</strong>
                      <Progress value={bestBet.probability} tone="green" />
                    </div>
                    <div className="day-stat-card">
                      <span>РљРѕСЌС„С„РёС†РёРµРЅС‚</span>
                      <strong>{bestBet.odds ?? "вЂ”"}</strong>
                      <small>Р»СѓС‡С€РёР№ РґРѕСЃС‚СѓРїРЅС‹Р№</small>
                    </div>
                    <div className="day-stat-card value-card">
                      <span>Value</span>
                      <strong>{valuePercent(bestBet.value)}</strong>
                      <small>РїСЂРµРёРјСѓС‰РµСЃС‚РІРѕ РјРѕРґРµР»Рё</small>
                    </div>
                    <button className="day-bet-cta" type="button" onClick={() => document.getElementById("statistics")?.scrollIntoView({ behavior: "smooth" })}>
                      <TrendingUp size={24} />
                      РџРћР”Р РћР‘РќР«Р™ РђРќРђР›РР—
                      <ChevronRight size={24} />
                    </button>
                  </div>
                </div>

                <div className="day-bet-note">
                  <Sparkles size={18} />
                  <span>РњРѕРґРµР»СЊ РїРѕРєР°Р·С‹РІР°РµС‚ РІС‹СЃРѕРєСѓСЋ РІРµСЂРѕСЏС‚РЅРѕСЃС‚СЊ РїСЂРѕС…РѕРґР° РїСЂРё РїРѕР»РѕР¶РёС‚РµР»СЊРЅРѕРј Value <strong>{valuePercent(bestBet.value)}</strong> Рё Confidence <strong>{percentText(bestBet.confidence)}</strong>.</span>
                </div>
              </section>
            ) : (
              <section className="hero-bet-card no-value"><div className="bet-ribbon"><Trophy size={19} /> Р“Р›РђР’РќРђРЇ РЎРўРђР’РљРђ</div><div className="no-value-copy"><h2>РЎРµР№С‡Р°СЃ СЏРІРЅРѕР№ Value-СЃС‚Р°РІРєРё РЅРµС‚</h2><p>Р­С‚Рѕ С‚РѕР¶Рµ РїРѕР»РµР·РЅС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚: РјРѕРґРµР»СЊ РЅРµ РїСЂРµРґР»Р°РіР°РµС‚ СЃС‚Р°РІРєСѓ СЂР°РґРё СЃС‚Р°РІРєРё.</p></div></section>
            )}

            <div id="statistics" className="dashboard-grid">
              <section className="dashboard-main">
                <div className="panel-card">
                  <SectionTitle icon={<Layers3 size={20} />} title="Р’СЃРµ РІР°СЂРёР°РЅС‚С‹ СЃС‚Р°РІРѕРє" subtitle="РЎСЂР°РІРЅРµРЅРёРµ РІРµСЂРѕСЏС‚РЅРѕСЃС‚Рё, РєРѕСЌС„С„РёС†РёРµРЅС‚Р° Рё Value" badge={`${markets.length} СЂС‹РЅРєРѕРІ`} />
                  <div className="value-table-wrap">
                    <table className="value-table">
                      <thead><tr><th>РЎС‚Р°РІРєР°</th><th>Р’РµСЂРѕСЏС‚РЅРѕСЃС‚СЊ</th><th>Р›СѓС‡С€РёР№ РєСЌС„</th><th>Value</th><th>Confidence</th><th>РЎС‚Р°С‚СѓСЃ</th></tr></thead>
                      <tbody>
                        {(markets.length ? markets : bestBet ? [bestBet] : []).map((bet, index) => (
                          <tr key={`${bet.market}-${bet.selection}-${index}`} className={index === 0 ? "top-market" : ""}>
                            <td>
  <strong>{prettyBetLabel(bet)}</strong>
  <small>{prettyBetDescription(bet)}</small>
</td>
                            <td>{percentText(bet.probability)}</td>
                            <td><strong>{bet.odds ?? bet.coefficient ?? bet.price ?? "вЂ”"}</strong></td>
                            <td className={valueNumber(bet.value) > 0 ? "positive" : "negative"}>{valuePercent(bet.value)}</td>
                            <td><div className="confidence-cell"><span>{percentText(bet.confidence)}</span><Progress value={bet.confidence} tone="green" /></div></td>
                            <td><OddsStatus bet={bet} /></td>
                          </tr>
                        ))}
                        {!markets.length && !bestBet ? <tr><td colSpan="6" className="empty-table">РќРµС‚ СЂС‹РЅРєРѕРІ, РїСЂРѕС€РµРґС€РёС… С„РёР»СЊС‚СЂ Value/Confidence.</td></tr> : null}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="panel-card">
                  <SectionTitle icon={<TrendingUp size={20} />} title="Р¤РѕСЂРјР° Рё СЃРёР»Р° РєРѕРјР°РЅРґ" subtitle="РџРѕСЃР»РµРґРЅРёРµ РјР°С‚С‡Рё + РґРѕРјР°С€РЅСЏСЏ/РІС‹РµР·РґРЅР°СЏ С„РѕСЂРјР°" />
                  <div className="form-columns">
                    <div className="form-box"><div className="form-name"><strong>{result.match.home_team}</strong><span>РџРѕСЃР»РµРґРЅРёРµ РјР°С‚С‡Рё</span></div><div className="form-pills">{(result?.form?.home || []).map((x, i) => <FormPill result={x} key={i} />)}</div><div className="mini-stat-row"><span>Home PPG</span><strong>{number(result?.form?.home_home?.points_per_game)}</strong></div><div className="mini-stat-row"><span>Р—Р°Р±РёРІР°РµС‚</span><strong>{number(result?.attack?.home)}</strong></div><div className="mini-stat-row"><span>РџСЂРѕРїСѓСЃРєР°РµС‚</span><strong>{number(result?.defense?.home)}</strong></div></div>
                    <div className="form-box"><div className="form-name"><strong>{result.match.away_team}</strong><span>РџРѕСЃР»РµРґРЅРёРµ РјР°С‚С‡Рё</span></div><div className="form-pills">{(result?.form?.away || []).map((x, i) => <FormPill result={x} key={i} />)}</div><div className="mini-stat-row"><span>Away PPG</span><strong>{number(result?.form?.away_away?.points_per_game)}</strong></div><div className="mini-stat-row"><span>Р—Р°Р±РёРІР°РµС‚</span><strong>{number(result?.attack?.away)}</strong></div><div className="mini-stat-row"><span>РџСЂРѕРїСѓСЃРєР°РµС‚</span><strong>{number(result?.defense?.away)}</strong></div></div>
                  </div>
                </div>

                <div className="two-panels">
                  <div className="panel-card compact-panel"><SectionTitle icon={<Goal size={20} />} title="Р“РѕР»С‹" subtitle="Р’РµСЂРѕСЏС‚РЅРѕСЃС‚Рё С‚РѕС‚Р°Р»РѕРІ" /><div className="metric-list"><div><span>Over 1.5</span><strong>{percentText(goals.over_1_5)}</strong></div><div><span>Over 2.5</span><strong className="positive">{percentText(goals.over_2_5)}</strong></div><div><span>Under 2.5</span><strong>{percentText(goals.under_2_5)}</strong></div><div><span>Over 3.5</span><strong>{percentText(goals.over_3_5)}</strong></div></div></div>
                  <div className="panel-card compact-panel"><SectionTitle icon={<Swords size={20} />} title="РћР±Рµ Р·Р°Р±СЊСЋС‚ / H2H" subtitle="Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ СЃРёРіРЅР°Р»С‹" /><div className="metric-list"><div><span>РћР— вЂ” Р”Р°</span><strong className="positive">{percentText(btts.yes)}</strong></div><div><span>РћР— вЂ” РќРµС‚</span><strong>{percentText(btts.no)}</strong></div><div><span>H2H РјР°С‚С‡РµР№</span><strong>{result?.h2h?.matches ?? 0}</strong></div><div><span>РўРѕРї СЃС‡С‘С‚</span><strong>{likelyScore ? `${likelyScore.home}:${likelyScore.away}` : "вЂ”"}</strong></div></div></div>
                </div>

                <div className="panel-card"><SectionTitle icon={<CircleDollarSign size={20} />} title="Р›СѓС‡С€РёРµ СЂРµР°Р»СЊРЅС‹Рµ РєРѕСЌС„С„РёС†РёРµРЅС‚С‹" subtitle={`${result?.bookmakers_count ?? 0} Р±СѓРєРјРµРєРµСЂРѕРІ РІ СЃРѕР±С‹С‚РёРё`} badge="THE ODDS API" /><div className="odds-grid">{[["Рџ1", odds["1"]],["X", odds.X],["Рџ2", odds["2"]],["1X", odds["1X"]],["X2", odds.X2],["РўР‘ 2.5", odds.over_2_5],["РўРњ 2.5", odds.under_2_5],["РћР— Р”Р°", odds.btts_yes],["РћР— РќРµС‚", odds.btts_no]].map(([label, val]) => <div className="odds-box" key={label}><span>{label}</span><strong>{val ?? "вЂ”"}</strong></div>)}</div></div>
              </section>

              <aside className="dashboard-side">
                <div className="side-card outcome-card"><SectionTitle icon={<Target size={20} />} title="Р’РµСЂРѕСЏС‚РЅРѕСЃС‚Рё РёСЃС…РѕРґР°" /><div className="outcome-row"><div><span>Рџ1</span><strong>{percentText(prediction.home)}</strong><Progress value={prediction.home} tone="green" /></div><div><span>X</span><strong>{percentText(prediction.draw)}</strong><Progress value={prediction.draw} tone="blue" /></div><div><span>Рџ2</span><strong>{percentText(prediction.away)}</strong><Progress value={prediction.away} tone="red" /></div></div><div className="double-chance"><span>1X <strong>{percentText(prediction.double_home)}</strong></span><span>X2 <strong>{percentText(prediction.double_away)}</strong></span></div></div>

                <div className="side-card"><SectionTitle icon={<BarChart3 size={20} />} title="РћР¶РёРґР°РµРјС‹Рµ РіРѕР»С‹ (xG)" /><div className="xg-versus"><div><span>{result.match.home_team}</span><strong>{number(xg.home, 3)}</strong><Progress value={Math.min(100, pct(xg.home) * 28)} tone="yellow" /></div><div className="xg-divider" /><div><span>{result.match.away_team}</span><strong>{number(xg.away, 3)}</strong><Progress value={Math.min(100, pct(xg.away) * 28)} tone="green" /></div></div><div className="mini-stat-row"><span>Base xG</span><strong>{number(xg.base_home, 3)} / {number(xg.base_away, 3)}</strong></div><div className="mini-stat-row"><span>REAL xG sample</span><strong>{xg?.real?.home_sample ?? "вЂ”"} / {xg?.real?.away_sample ?? "вЂ”"}</strong></div><div className="mini-stat-row"><span>РСЃС‚РѕСЂРёСЏ</span><strong>{result?.history?.home_matches ?? 0} / {result?.history?.away_matches ?? 0}</strong></div></div>

                <div className="side-card"><SectionTitle icon={<Flag size={20} />} title="РђРЅР°Р»РёР· СѓРіР»РѕРІС‹С…" badge={cornersAvailable ? "LIVE" : "N/A"} />{cornersAvailable ? <><div className="corner-versus"><div><span>{result.match.home_team}</span><strong>{number(corners.home, 2)}</strong></div><div><span>{result.match.away_team}</span><strong>{number(corners.away, 2)}</strong></div></div><div className="corner-total-box"><span>РћР¶РёРґР°РµРјС‹Р№ С‚РѕС‚Р°Р»</span><strong>{number(corners.total, 2)}</strong></div>{cornersQuality ? <div className="quality-block"><div className="quality-ring" style={{ "--quality": `${Math.min(100, cornersQuality) * 3.6}deg` }}><span>{Math.round(cornersQuality)}%</span></div><div><strong>РљР°С‡РµСЃС‚РІРѕ РїСЂРѕРіРЅРѕР·Р°</strong><span>РЎС‚Р°Р±РёР»СЊРЅРѕСЃС‚СЊ РјРѕРґРµР»Рё СѓРіР»РѕРІС‹С…</span></div></div> : null}</> : <div className="empty-side">{corners?.message || "Р”Р°РЅРЅС‹Рµ СѓРіР»РѕРІС‹С… РЅРµРґРѕСЃС‚СѓРїРЅС‹."}</div>}</div>
                <div className="side-card cards-side">
                  <SectionTitle
                    icon={<Shield size={20} />}
                    title="Р–С‘Р»С‚С‹Рµ РєР°СЂС‚РѕС‡РєРё"
                    badge={cardsAvailable ? `${Math.min(cards?.home?.sample || 0, cards?.away?.sample || 0)}/30` : "N/A"}
                  />
                  {cardsAvailable ? (
                    <>
                      <div className="cards-versus">
                        <div>
                          <span>{result.match.home_team}</span>
                          <strong>{number(cards?.home?.average, 2)}</strong>
                          <small>СЃСЂРµРґРЅРµРµ Р·Р° {cards?.home?.sample || 0} РјР°С‚С‡РµР№</small>
                        </div>
                        <div>
                          <span>{result.match.away_team}</span>
                          <strong>{number(cards?.away?.average, 2)}</strong>
                          <small>СЃСЂРµРґРЅРµРµ Р·Р° {cards?.away?.sample || 0} РјР°С‚С‡РµР№</small>
                        </div>
                      </div>

                      <div className="cards-total-box">
                        <div>
                          <span>РЎСЂРµРґРЅРёР№ С‚РѕС‚Р°Р» РєРѕРјР°РЅРґ</span>
                          <strong>{number(cards?.team_total_average, 2)}</strong>
                        </div>
                        <div>
                          <span>РћР¶РёРґР°РµРјС‹Р№ С‚РѕС‚Р°Р»</span>
                          <strong>{number(cards?.expected_total, 2)}</strong>
                        </div>
                      </div>

                      <div className="referee-card">
                        <div className="referee-icon">рџ§‘вЂЌвљ–пёЏ</div>
                        <div className="referee-copy">
                          <span>РђСЂР±РёС‚СЂ РјР°С‚С‡Р°</span>
                          <strong>{referee?.name || "РџРѕРєР° РЅРµ РЅР°Р·РЅР°С‡РµРЅ"}</strong>
                          {referee?.assigned ? (
                            <small>
                              {referee?.yellow_average != null
                                ? `${number(referee.yellow_average, 2)} Р¶С‘Р»С‚С‹С… Р·Р° РјР°С‚С‡`
                                : "РЎСЂРµРґРЅРµРµ РїРѕ РєР°СЂС‚РѕС‡РєР°Рј РЅРµРґРѕСЃС‚СѓРїРЅРѕ"}
                              {referee?.matches ? ` В· ${referee.matches} РјР°С‚С‡РµР№` : ""}
                            </small>
                          ) : (
                            <small>{referee?.message || "Р”Р°РЅРЅС‹Рµ Р°СЂР±РёС‚СЂР° РїРѕРєР° РЅРµ РѕРїСѓР±Р»РёРєРѕРІР°РЅС‹"}</small>
                          )}
                        </div>
                      </div>

                      {cardsQuality ? (
                        <div className="cards-quality-row">
                          <span>РљР°С‡РµСЃС‚РІРѕ РґР°РЅРЅС‹С…</span>
                          <Progress value={cardsQuality} tone="yellow" />
                          <strong>{Math.round(cardsQuality)}%</strong>
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="empty-side">{cards?.message || "Р”Р°РЅРЅС‹Рµ РїРѕ Р¶С‘Р»С‚С‹Рј РєР°СЂС‚РѕС‡РєР°Рј РЅРµРґРѕСЃС‚СѓРїРЅС‹."}</div>
                  )}
                </div>

                <div className="side-card ai-side"><SectionTitle icon={<Brain size={20} />} title="AI Assessment" /><div className="ai-score-row"><div><span>Rating</span><strong>{ai.rating ?? "вЂ”"}</strong></div><div><span>Risk</span><strong>{ai.risk ?? "вЂ”"}</strong></div></div><p>{ai.summary || modelRecommendation}</p></div>
              </aside>
            </div>

            {bestBet ? (
              <div className="mobile-value-dock">
                <div><span>TOP VALUE</span><strong>{bestBet.selection || bestBet.market}</strong></div>
                <div><span>Value</span><strong>{valuePercent(bestBet.value)}</strong></div>
                <div><span>РљСЌС„</span><strong>{bestBet.odds ?? "вЂ”"}</strong></div>
              </div>
            ) : null}

            <section id="about" className="trust-strip">
              <div><div className="trust-icon green"><BarChart3 size={22} /></div><span><strong>Р РµР°Р»СЊРЅС‹Рµ РєРѕСЌС„С„РёС†РёРµРЅС‚С‹</strong><small>РЎСЂР°РІРЅРµРЅРёРµ РґРѕСЃС‚СѓРїРЅС‹С… Р±СѓРєРјРµРєРµСЂРѕРІ</small></span></div>
              <div><div className="trust-icon blue"><Database size={22} /></div><span><strong>Р“Р»СѓР±РѕРєРёР№ Р°РЅР°Р»РёР·</strong><small>xG, С„РѕСЂРјР°, H2H Рё Poisson</small></span></div>
              <div><div className="trust-icon purple"><Zap size={22} /></div><span><strong>РџРѕРёСЃРє Value</strong><small>Р’РµСЂРѕСЏС‚РЅРѕСЃС‚СЊ РїСЂРѕС‚РёРІ СЂС‹РЅРѕС‡РЅРѕР№ С†РµРЅС‹</small></span></div>
              <div><div className="trust-icon orange"><Shield size={22} /></div><span><strong>Р‘РµР· С„РµР№РєРѕРІС‹С… РґР°РЅРЅС‹С…</strong><small>РќРµС‚ РґР°РЅРЅС‹С… вЂ” С‚Р°Рє Рё РїРѕРєР°Р·С‹РІР°РµРј</small></span></div>
            </section>

            <footer className="site-footer"><div className="footer-brand"><LogoMark /><strong>FootballAI</strong></div><span>Р¤СѓС‚Р±РѕР» вЂ” СЌС‚Рѕ Р±РѕР»СЊС€Рµ, С‡РµРј РёРіСЂР°. Р­С‚Рѕ РґР°РЅРЅС‹Рµ. Р­С‚Рѕ РІРѕР·РјРѕР¶РЅРѕСЃС‚Рё.</span><span>{result?.version || "Football AI Analyst"}</span></footer>
          </div>
        ) : null}
      </main>
      {activePage === "statistics" ? <StatisticsPage /> : null}
      {activePage === "about" ? <AboutPage /> : null}
    </div>
  );
}

export default App;

