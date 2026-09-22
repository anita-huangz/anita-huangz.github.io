import type { ComponentType } from "react";

import { CacheDemo } from "./components/CacheDemo";
import { CardsDemo } from "./components/CardsDemo";
import { CurveDemo } from "./components/CurveDemo";
import { EarningsDemo } from "./components/EarningsDemo";
import { FactorDemo } from "./components/FactorDemo";
import { PianoDemo } from "./components/PianoDemo";
import { ScheduleDemo } from "./components/ScheduleDemo";
import { TrieDemo } from "./components/TrieDemo";
import {
  BitcoinDemo,
  StockBondDemo,
  WeatherDemo,
} from "./components/QuantDemos";
import {
  ChurnDemo,
  FakeNewsDemo,
  RecommendDemo,
  ThreatsDemo,
} from "./components/NotebookDemos";

/**
 * Project slug -> live demo. A project without an entry simply renders its
 * write-up, so adding a demo never requires touching the detail panel.
 */
export const DEMOS: Record<string, { title: string; component: ComponentType }> = {
  "factor-based-portfolio-simulator": {
    title: "Run the backtest",
    component: FactorDemo,
  },
  "yield-curve-lab": {
    title: "Build a curve trade",
    component: CurveDemo,
  },
  "earnings-drift-tracker": {
    title: "Explore the drift",
    component: EarningsDemo,
  },
  "trie-search": {
    title: "Search the index",
    component: TrieDemo,
  },
  "course-catalog": {
    title: "Build a schedule",
    component: ScheduleDemo,
  },
  "card-game-system": {
    title: "Play a round",
    component: CardsDemo,
  },
  "fastcache": {
    title: "Watch the cache evict",
    component: CacheDemo,
  },
  "customer-churn-prediction": {
    title: "See what the model caught and missed",
    component: ChurnDemo,
  },
  "fake-news-detection": {
    title: "See why this one does not work",
    component: FakeNewsDemo,
  },
  "global-security-threats": {
    title: "Compare the clusters against noise",
    component: ThreatsDemo,
  },
  "personalized-recommendations-for-e-commerce": {
    title: "Score the recommenders",
    component: RecommendDemo,
  },
  "stock-bond-portfolio-analysis": {
    title: "Solve the allocation",
    component: StockBondDemo,
  },
  "bitcoin-and-asset-trading": {
    title: "See the model against a one-line baseline",
    component: BitcoinDemo,
  },
  "weather-trends-and-forecast": {
    title: "Chart the trend",
    component: WeatherDemo,
  },
  "piano-arrangement-lab": {
    title: "Arrange something",
    component: PianoDemo,
  },
};

export function hasDemo(slug: string): boolean {
  return slug in DEMOS;
}
