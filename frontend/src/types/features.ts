import { tr } from '@/i18n';
import type { BotState } from '@/types';

export interface FeatureConfig {
  minVersion?: number;
  maxVersion?: number;
  condition?: (botState: BotState, apiVersion: number) => boolean;
  description?: string;
}
export type FeatureKey =
  | 'forceExitParams'
  | 'botBlacklistModify'
  | 'futures'
  | 'forceEnterShort'
  | 'advancedDailyMetrics'
  | 'forceEntryTag'
  | 'cancelOpenOrders'
  | 'reloadTrade'
  | 'plotConfigFromServer'
  | 'weeklyMonthlyStats'
  | 'websocketConnection'
  | 'websocketNewCandle'
  | 'reducedPairCalls'
  | 'hasBotBalance'
  | 'hasAdvancedStats'
  | 'chartLiveData'
  | 'hasProfitAll'
  | 'backtestHistory'
  | 'backtestFreqAI'
  | 'backtestDelete'
  | 'backtestSetNotes'
  | 'downloadDataView'
  | 'pairlistConfig'
  | 'downloadDataCandleTypes'
  | 'forceExitWithPrice'
  | 'downloadDataPrepend'
  | 'strategyParameters'
  | 'walletChange'
  | 'recursiveAnalysis'
  | 'lookaheadAnalysis'
  | 'backgroundJobDelete'
  | 'timerangeWithTime'
  | 'strategyParametersModify'
  | 'backtestPairHistory';

export type BotFeatures = Record<FeatureKey, boolean>;

export const FEATURES: Record<FeatureKey, FeatureConfig> = {
  // Core features
  forceExitParams: {
    minVersion: 1.2,
    get description() {
      return tr('Force exit with parameters');
    },
  },
  botBlacklistModify: {
    minVersion: 1.12,
    get description() {
      return tr('Modify bot pairlist');
    },
  },
  futures: {
    minVersion: 2.0,
    get description() {
      return tr('Futures');
    },
  }, // TODO: Could be consolidated
  forceEnterShort: {
    minVersion: 2.13,
    get description() {
      return tr('Force enter short position');
    },
  },
  advancedDailyMetrics: {
    minVersion: 2.16,
    get description() {
      return tr('Advanced daily metrics');
    },
  },
  forceEntryTag: {
    minVersion: 2.17,
    get description() {
      return tr('Force enter - set entry tag, Force Exit partial');
    },
  },
  cancelOpenOrders: {
    minVersion: 2.24,
    get description() {
      return tr('Cancel open orders');
    },
  },
  reloadTrade: {
    minVersion: 2.28,
    get description() {
      return tr('Reload trade');
    },
  },
  plotConfigFromServer: {
    minVersion: 2.23,
    get description() {
      return tr('Load plot configuration from backend');
    },
  },
  weeklyMonthlyStats: {
    minVersion: 2.33,
    get description() {
      return tr('Weekly/monthly stats');
    },
  },
  websocketConnection: {
    minVersion: 2.2,
    get description() {
      return tr('WebSocket connection support');
    },
  },
  websocketNewCandle: {
    minVersion: 2.21,
    get description() {
      return tr('WebSocket new candle datatype');
    },
  },

  reducedPairCalls: {
    minVersion: 2.35,
    get description() {
      return tr('Modern pair candles API');
    },
  },
  hasBotBalance: {
    minVersion: 2.26,
    get description() {
      return tr('Provides bot balance');
    },
  },
  hasAdvancedStats: {
    minVersion: 2.34,
    get description() {
      return tr('new entries/exits/mix_tags endpoints');
    },
  },
  chartLiveData: {
    minVersion: 2.42,
    get description() {
      return tr('Live chart data support in webserver mode');
    },
  },
  hasProfitAll: {
    minVersion: 2.43,
    get description() {
      return tr('Profit all endpoint');
    },
  },
  // Backtesting
  backtestHistory: {
    minVersion: 2.15,
    get description() {
      return tr('Can Run Backtests');
    },
  },
  backtestFreqAI: {
    minVersion: 2.22,
    get description() {
      return tr('FreqAI support for backtesting');
    },
  },
  backtestDelete: {
    minVersion: 2.31,
    get description() {
      return tr('Delete backtest endpoints');
    },
  },
  backtestSetNotes: {
    minVersion: 2.32,
    get description() {
      return tr('Set notes for backtest results');
    },
  },
  // Overall Webserver features
  downloadDataView: {
    minVersion: 2.41,
    get description() {
      return tr('Download data View');
    },
  },
  pairlistConfig: {
    minVersion: 2.3,
    get description() {
      return tr('Configure pairlist for bot');
    },
  },
  downloadDataCandleTypes: {
    minVersion: 2.44,
    get description() {
      return tr('Candle type selection for data download');
    },
  },
  forceExitWithPrice: {
    minVersion: 2.45,
    get description() {
      return tr('Force exit accepting price parameter');
    },
  },
  downloadDataPrepend: {
    minVersion: 2.46,
    get description() {
      return tr('Prepend data when downloading');
    },
  },
  strategyParameters: {
    minVersion: 2.47,
    get description() {
      return tr('Strategy parameters');
    },
  },
  walletChange: {
    minVersion: 2.48,
    get description() {
      return tr('Wallet change data endpoint');
    },
  },
  recursiveAnalysis: {
    minVersion: 2.49,
    get description() {
      return tr('Recursive analysis');
    },
  },
  lookaheadAnalysis: {
    minVersion: 2.49,
    get description() {
      return tr('Lookahead analysis');
    },
  },
  backgroundJobDelete: {
    minVersion: 2.49,
    get description() {
      return tr('Delete background jobs');
    },
  },
  timerangeWithTime: {
    minVersion: 2.5,
    get description() {
      return tr('Timerange with hour/minute precision');
    },
  },
  strategyParametersModify: {
    minVersion: 2.51,
    get description() {
      return tr('Strategy parameter setting');
    },
  },
  backtestPairHistory: {
    minVersion: 2.51,
    get description() {
      return tr('Analyze pairs with the strategy stored in a backtest result');
    },
  },
};
