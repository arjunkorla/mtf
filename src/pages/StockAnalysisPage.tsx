import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, TrendingUp, AlertCircle } from "lucide-react";
import { StockAnalysisResponse } from "../types/stock";
import { getStockAnalysis } from "../api/stockApi";
import Badge, { SignalQualityBadge } from "../components/ui/Badge";
import ScoreRing from "../components/ui/ScoreRing";
import ScoreBreakdownBar from "../components/ui/ScoreBreakdownBar";
import WhySelectedSection from "../components/analysis/WhySelected";
import InstitutionalFootprintSection from "../components/analysis/InstitutionalFootprint";
import TechnicalSetupSection from "../components/analysis/TechnicalSetup";
import FOAnalysisSection from "../components/analysis/FOAnalysis";
import FundamentalsSection from "../components/analysis/Fundamentals";
import SectorRelativeStrengthSection from "../components/analysis/SectorRelativeStrength";
import CatalystNewsSection from "../components/analysis/CatalystNews";
import RiskAnalysisSection from "../components/analysis/RiskAnalysis";
import TradeScenarioSection from "../components/analysis/TradeScenario";
import PositionSizingSection from "../components/analysis/PositionSizing";
import AIResearchSummarySection from "../components/analysis/AIResearchSummary";
import LiveMarketData from "../components/analysis/LiveMarketData";
import RealtimeConfirmation from "../components/analysis/RealtimeConfirmation";

const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";

function fmt(n: number) {
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

type Section = "why" | "footprint" | "technical" | "fo" | "fundamentals" | "sector" | "catalysts" | "risks" | "trade" | "sizing" | "summary";

const NAV_ITEMS: { id: Section; label: string }[] = [
  { id: "why", label: "Why Selected" },
  { id: "footprint", label: "Institutional Footprint" },
  { id: "technical", label: "Technical" },
  { id: "fo", label: "F&O" },
  { id: "fundamentals", label: "Fundamentals" },
  { id: "sector", label: "Sector / RS" },
  { id: "catalysts", label: "Catalysts" },
  { id: "risks", label: "Risks" },
  { id: "trade", label: "Trade Scenario" },
  { id: "sizing", label: "Position Sizing" },
  { id: "summary", label: "AI Summary" },
];

export default function StockAnalysisPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const [analysis, setAnalysis] = useState<StockAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [activeSection, setActiveSection] = useState<Section>("why");

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    getStockAnalysis(symbol)
      .then((data) => {
        if (data) {
          setAnalysis(data);
        } else {
          setNotFound(true);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load analysis"))
      .finally(() => setLoading(false));
  }, [symbol]);

  function scrollTo(id: Section) {
    setActiveSection(id);
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#080B10] flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="relative w-12 h-12 mx-auto">
            <div className="w-12 h-12 border-2 border-[#1A2540] rounded-full" />
            <div className="w-12 h-12 border-2 border-transparent border-t-[#CF8B2E] rounded-full animate-spin absolute top-0 left-0" />
          </div>
          <p className="text-sm font-heading text-[#64748B]">Loading analysis for {symbol}â€¦</p>
        </div>
      </div>
    );
  }

  if (error || notFound || !analysis) {
    return (
      <div className="min-h-screen bg-[#080B10] flex items-center justify-center">
        <div className="text-center space-y-4 max-w-sm px-5">
          <AlertCircle size={32} className="text-[#F05252] mx-auto" />
          <p className="text-sm font-heading font-semibold text-white">Analysis Unavailable</p>
          <p className="text-xs text-[#475569]">
            {error ? error : `${symbol} was not found in the configured stock universe.`}
          </p>
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 mx-auto text-xs font-heading uppercase tracking-widest text-[#CF8B2E] hover:text-white border border-[#CF8B2E] hover:bg-[#CF8B2E] px-4 py-2 rounded transition-colors"
          >
            <ArrowLeft size={12} />
            Back to Scanner
          </button>
        </div>
      </div>
    );
  }

  const { candidate } = analysis;
  const whySummary = analysis.ai_research?.sections["WHY WAS THIS STOCK SELECTED?"] ?? "AI research is not available for this candidate.";

  return (
    <div className="min-h-screen bg-[#080B10]">
      {/* Top nav */}
      <header className="border-b border-[#1A2540] bg-[#080B10] sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-5 py-3.5 flex items-center gap-4">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-1.5 text-xs font-heading text-[#64748B] hover:text-[#E2E8F0] transition-colors shrink-0"
          >
            <ArrowLeft size={13} />
            Scanner
          </button>
          <div className="w-px h-4 bg-[#1A2540]" />
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <TrendingUp size={13} className="text-[#CF8B2E] shrink-0" />
            <span className="font-heading font-bold text-sm text-white truncate">{analysis.symbol}</span>
            <span className="text-[#475569] text-xs hidden sm:block truncate">{analysis.company_name}</span>
          </div>
          {USE_MOCK && <span className="text-[10px] font-data text-[#475569] shrink-0">MOCK DATA</span>}
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-5 py-6">
        {/* Hero header */}
        <div className="border border-[#1A2540] rounded-lg bg-[#0F1520] p-5 mb-6">
          <div className="flex flex-wrap gap-6 items-start">
            {/* Score ring */}
            <div className="flex flex-col items-center gap-1 shrink-0">
              <ScoreRing score={candidate.score} size="lg" />
              <span className="text-[9px] font-heading text-[#475569] uppercase tracking-widest text-center leading-tight">
                MTF Setup<br />Score
              </span>
            </div>

            {/* Name + meta */}
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <h1 className="font-heading font-bold text-2xl sm:text-3xl text-white tracking-tight">
                  {analysis.company_name}
                </h1>
              </div>
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <span className="font-data text-sm text-[#64748B]">{analysis.symbol}</span>
                {candidate.sector && (
                  <>
                    <span className="text-[#1A2540]">·</span>
                    <span className="text-sm text-[#64748B] font-heading">{candidate.sector}</span>
                  </>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <SignalQualityBadge quality={candidate.signal_quality} />
                <Badge variant="neutral">Data Quality {candidate.data_quality.data_quality_score.toFixed(0)}%</Badge>
                <Badge variant="neutral">{candidate.setup.setup_type.replace(/_/g, " ")}</Badge>
              </div>
            </div>

            {/* Current price */}
            <div className="flex flex-wrap gap-3 self-start">
              <div className="text-right">
                <div className="text-[9px] font-heading uppercase tracking-widest text-[#475569]">Current Price</div>
                <div className="font-data font-bold text-2xl text-white mt-0.5">{fmt(analysis.market_data.price)}</div>
                {analysis.market_data.change_pct !== null && (
                  <div className={`font-data text-xs mt-0.5 ${analysis.market_data.change_pct >= 0 ? "text-[#22C9B4]" : "text-[#F05252]"}`}>
                    {analysis.market_data.change_pct >= 0 ? "+" : ""}
                    {analysis.market_data.change_pct.toFixed(2)}%
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Score breakdown */}
          <div className="mt-5 pt-5 border-t border-[#1A2540]">
            <div className="text-[10px] font-heading uppercase tracking-widest text-[#475569] mb-3">
              Score Breakdown
            </div>
            <ScoreBreakdownBar components={candidate.score_components} />
          </div>
        </div>

        {/* Live market data + real-time confirmation -- both render nothing
            if unavailable, and are kept visually separate from the MTF
            structural score above (never combined into one number) */}
        <div className="mb-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <LiveMarketData symbol={analysis.symbol} />
          <RealtimeConfirmation symbol={analysis.symbol} />
        </div>

        <div className="flex gap-6 items-start">
          {/* Sidebar nav (desktop) */}
          <nav className="hidden xl:block w-44 shrink-0 sticky top-20">
            <div className="border border-[#1A2540] rounded-lg bg-[#0F1520] overflow-hidden">
              {NAV_ITEMS.map((item) => (
                <button
                  key={item.id}
                  onClick={() => scrollTo(item.id)}
                  className={`w-full text-left px-4 py-2.5 text-xs font-heading transition-colors border-b border-[#1A2540] last:border-b-0 ${
                    activeSection === item.id ? "text-[#CF8B2E] bg-[#1A1C0E]" : "text-[#64748B] hover:text-[#94A3B8] hover:bg-[#0B1018]"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </nav>

          {/* Main content */}
          <div className="flex-1 min-w-0 space-y-5">
            <div id="section-why">
              <WhySelectedSection summary={whySummary} evidence={candidate.evidence} />
            </div>
            <div id="section-footprint">
              <InstitutionalFootprintSection data={candidate.institutional_footprint} />
            </div>
            <div id="section-technical">
              <TechnicalSetupSection data={candidate.technical} volume={candidate.volume} />
            </div>
            <div id="section-fo">
              <FOAnalysisSection data={candidate.fno} />
            </div>
            <div id="section-fundamentals">
              <FundamentalsSection data={candidate.fundamentals} />
            </div>
            <div id="section-sector">
              <SectorRelativeStrengthSection data={candidate.sector_context} />
            </div>
            <div id="section-catalysts">
              <CatalystNewsSection data={candidate.news} />
            </div>
            <div id="section-risks">
              <RiskAnalysisSection risks={candidate.risks} invalidationCondition={candidate.setup.invalidation_condition} />
            </div>
            <div id="section-trade">
              <TradeScenarioSection scenarios={candidate.scenarios} positionSizing={candidate.position_sizing} />
            </div>
            <div id="section-sizing">
              <PositionSizingSection data={candidate.position_sizing} />
            </div>
            <div id="section-summary">
              <AIResearchSummarySection data={analysis.ai_research} />
            </div>

            <p className="text-[10px] text-[#374151] text-center leading-relaxed mt-8 pb-8">
              This application is a research tool. It does not place trades, manage positions, or provide financial
              advice. All output is for informational purposes only. Always conduct your own analysis and apply your
              own risk management before entering any position.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
