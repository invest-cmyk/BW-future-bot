"""
News Collector + Reporter Agent
================================
Pulls live financial headlines from free RSS sources, scores sentiment,
builds a structured report, and sends both a trading signal and the
full report to the Boss.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import hashlib

import pandas as pd

try:
    import feedparser
    import requests
    HAS_FEED = True
except ImportError:
    HAS_FEED = False

from agents.base import BaseAgent
from core.models import Signal, Side


# ---------------------------------------------------------------------------
# Report object that travels to the Boss
# ---------------------------------------------------------------------------
@dataclass
class NewsReport:
    """Structured news briefing delivered to the Boss each cycle."""
    timestamp: datetime
    symbols_covered: List[str]
    headlines: List[dict]          # [{title, source, link, published, sentiment}]
    summary: str                   # short executive summary
    overall_bias: str              # BULLISH / BEARISH / NEUTRAL
    bias_score: float              # -1.0 … +1.0
    key_risks: List[str]
    per_symbol: Dict[str, dict]    # symbol → {bias, score, top_headlines}
    raw_count: int = 0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_bias": self.overall_bias,
            "bias_score": round(self.bias_score, 3),
            "summary": self.summary,
            "key_risks": self.key_risks,
            "headlines_used": self.raw_count,
            "per_symbol": self.per_symbol,
        }

    def pretty(self) -> str:
        lines = [
            f"📰 NEWS REPORT  {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Overall bias : {self.overall_bias} ({self.bias_score:+.2f})",
            f"Headlines    : {self.raw_count}",
            "",
            "Summary:",
            self.summary,
            "",
        ]
        if self.key_risks:
            lines.append("Key risks:")
            for r in self.key_risks:
                lines.append(f"  • {r}")
            lines.append("")
        for sym, info in self.per_symbol.items():
            lines.append(f"{sym}: {info.get('bias', 'N/A')} ({info.get('score', 0):+.2f})")
            for h in info.get("top_headlines", [])[:2]:
                lines.append(f"   – {h}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Free RSS sources (no API key required)
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    # Broad market
    "https://finance.yahoo.com/news/rssindex",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",          # Top News
    "https://www.cnbc.com/id/15839135/device/rss/rss.html",           # Finance
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://feeds.reuters.com/reuters/businessNews",
    # Futures / commodities focused
    "https://www.investing.com/rss/news_25.rss",                    # commodities
    "https://www.investing.com/rss/news_1.rss",                     # market overview
]

# Keyword maps for simple but effective sentiment
BULLISH = {
    "rally", "surge", "jump", "gain", "gains", "rise", "rises", "rose",
    "bullish", "optimism", "optimistic", "recovery", "rebound", "record high",
    "beat", "beats", "strong", "strength", "upbeat", "soar", "soars",
    "growth", "expansion", "support", "supported", "demand", "buying",
    "soft landing", "rate cut", "easing", "dovish",
}
BEARISH = {
    "fall", "falls", "fell", "drop", "drops", "slump", "slide", "selloff",
    "sell-off", "bearish", "fear", "worries", "concern", "risk", "risks",
    "weak", "weakness", "miss", "misses", "cut", "cuts", "layoff", "layoffs",
    "recession", "inflation", "hawkish", "tightening", "tariff", "war",
    "geopolitical", "default", "crisis", "crash", "plunge",
}

# Symbol-specific keyword boosts
SYMBOL_KEYWORDS = {
    "ES":  {"s&p", "spx", "sp500", "equity", "stocks", "wall street", "fed", "fomc"},
    "NQ":  {"nasdaq", "nasdaq-100", "tech", "megacap", "ai", "semiconductor", "nvda", "apple", "microsoft"},
    "CL":  {"oil", "crude", "wti", "brent", "opec", "energy", "petroleum", "gasoline"},
    "GC":  {"gold", "bullion", "xau", "safe-haven", "safe haven", "precious metal"},
}


def _sentiment_score(text: str) -> float:
    """Return score in [-1, +1] from keyword hits."""
    text = text.lower()
    score = 0.0
    for w in BULLISH:
        if w in text:
            score += 0.22
    for w in BEARISH:
        if w in text:
            score -= 0.22
    return max(min(score, 1.0), -1.0)


def _relevant_to_symbol(text: str, symbol: str) -> bool:
    keys = SYMBOL_KEYWORDS.get(symbol, set())
    text_l = text.lower()
    return any(k in text_l for k in keys) or symbol.lower() in text_l


def _fetch_rss(url: str, timeout: int = 8) -> List[dict]:
    if not HAS_FEED:
        return []
    try:
        # feedparser can take a URL directly; requests gives better timeout control
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "FuturesAutopilot/1.0 (research bot)"
        })
        if resp.status_code != 200:
            return []
        parsed = feedparser.parse(resp.content)
        items = []
        for e in parsed.entries[:15]:
            title = getattr(e, "title", "") or ""
            link = getattr(e, "link", "") or ""
            published = getattr(e, "published", "") or getattr(e, "updated", "")
            summary = getattr(e, "summary", "") or ""
            # strip html tags from summary
            summary = re.sub(r"<[^>]+>", "", summary)[:300]
            items.append({
                "title": title.strip(),
                "link": link,
                "published": published,
                "summary": summary.strip(),
                "source": parsed.feed.get("title", url)[:40],
            })
        return items
    except Exception:
        return []


def _dedupe(items: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for it in items:
        key = hashlib.md5(it["title"].lower().encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# The Agent
# ---------------------------------------------------------------------------
class NewsCollectorAgent(BaseAgent):
    """
    Collects live news → builds NewsReport → emits trading signals
    and attaches the full report so the Boss can log / display it.
    """

    def __init__(self, agent_id: str = "news_collector_1", weight: float = 0.65,
                 max_headlines: int = 40):
        super().__init__(agent_id, weight)
        self.max_headlines = max_headlines
        self.last_report: Optional[NewsReport] = None

    # ------------------------------------------------------------------
    def collect_headlines(self) -> List[dict]:
        all_items = []
        for url in RSS_FEEDS:
            all_items.extend(_fetch_rss(url))
        all_items = _dedupe(all_items)
        # newest first if we have dates, otherwise keep order
        return all_items[: self.max_headlines]

    def build_report(self, headlines: List[dict],
                     symbols: List[str]) -> NewsReport:
        if not headlines:
            report = NewsReport(
                timestamp=datetime.now(timezone.utc),
                symbols_covered=symbols,
                headlines=[],
                summary="No fresh headlines retrieved this cycle.",
                overall_bias="NEUTRAL",
                bias_score=0.0,
                key_risks=[],
                per_symbol={s: {"bias": "NEUTRAL", "score": 0.0, "top_headlines": []} for s in symbols},
                raw_count=0,
            )
            self.last_report = report
            return report

        # Score every headline
        scored = []
        for h in headlines:
            text = f"{h['title']} {h.get('summary', '')}"
            s = _sentiment_score(text)
            h2 = dict(h)
            h2["sentiment"] = s
            scored.append(h2)

        # Overall market bias (all headlines)
        overall_scores = [h["sentiment"] for h in scored]
        overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0

        # Per-symbol
        per_symbol = {}
        for sym in symbols:
            relevant = [h for h in scored if _relevant_to_symbol(
                f"{h['title']} {h.get('summary', '')}", sym
            )]
            if not relevant:
                # fall back to overall if nothing specific
                per_symbol[sym] = {
                    "bias": "NEUTRAL",
                    "score": 0.0,
                    "top_headlines": [h["title"] for h in scored[:2]],
                }
                continue
            avg = sum(h["sentiment"] for h in relevant) / len(relevant)
            bias = "BULLISH" if avg > 0.12 else "BEARISH" if avg < -0.12 else "NEUTRAL"
            top = sorted(relevant, key=lambda x: abs(x["sentiment"]), reverse=True)[:3]
            per_symbol[sym] = {
                "bias": bias,
                "score": round(avg, 3),
                "top_headlines": [t["title"] for t in top],
            }

        # Key risks – headlines with strong negative sentiment
        risks = [
            h["title"] for h in sorted(scored, key=lambda x: x["sentiment"])
            if h["sentiment"] < -0.3
        ][:5]

        # Executive summary
        bias_label = "BULLISH" if overall > 0.12 else "BEARISH" if overall < -0.12 else "NEUTRAL"
        top_titles = [h["title"] for h in scored[:4]]
        summary = (
            f"Market tone appears {bias_label.lower()} (score {overall:+.2f}). "
            f"Top stories: " + " | ".join(top_titles)
        )
        if risks:
            summary += f" Notable risks: {risks[0]}"

        report = NewsReport(
            timestamp=datetime.now(timezone.utc),
            symbols_covered=symbols,
            headlines=scored,
            summary=summary,
            overall_bias=bias_label,
            bias_score=round(overall, 3),
            key_risks=risks,
            per_symbol=per_symbol,
            raw_count=len(scored),
        )
        self.last_report = report
        return report

    # ------------------------------------------------------------------
    def generate(self, market_data: Dict[str, pd.DataFrame]) -> List[Signal]:
        symbols = list(market_data.keys())
        headlines = self.collect_headlines()
        report = self.build_report(headlines, symbols)

        # Always print / log the report so the Boss (and user) can see it
        print("\n" + report.pretty() + "\n")

        signals = []
        for sym, info in report.per_symbol.items():
            score = info["score"]
            if abs(score) < 0.10:
                continue
            conf = min(abs(score) * 1.6, 0.85) * self.weight
            side = Side.LONG if score > 0 else Side.SHORT
            signals.append(Signal(
                agent_id=self.agent_id,
                symbol=sym,
                side=side,
                confidence=conf,
                size_contracts=1,
                stop_ticks=20,
                target_ticks=35,
                reason=f"News bias {info['bias']} ({score:+.2f}) | {info['top_headlines'][0][:60] if info['top_headlines'] else ''}",
                metadata={
                    "news_report": True,
                    "bias": info["bias"],
                    "score": score,
                    "overall_bias": report.overall_bias,
                }
            ))
        return signals

    def get_last_report(self) -> Optional[NewsReport]:
        return self.last_report
