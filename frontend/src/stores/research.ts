import { tr } from '@/i18n';
import type { FetchOptions } from 'ofetch';
import type {
  BacktestHistoryEntry,
  BacktestStatus,
  StrategyBacktestResult,
  StrategyListResult,
  StrategyResult,
} from '@/types';
import type { PreparationStatus, ResearchInfo } from '@/types/research';

export const useResearchStore = defineStore('research', () => {
  const bots = useBotStore();
  const info = ref<ResearchInfo>();
  const strategies = ref<string[]>([]);
  const strategy = ref('NostalgiaForInfinityX8');
  const now = new Date();
  const month = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const endDate = ref(month.toISOString().slice(0, 10));
  month.setUTCMonth(month.getUTCMonth() - 3);
  const startDate = ref(month.toISOString().slice(0, 10));
  const capital = ref(10000);
  const protections = ref(true);
  const status = ref<BacktestStatus>();
  const result = ref<StrategyBacktestResult>();
  const resultFilename = ref<string>();
  const history = ref<BacktestHistoryEntry[]>([]);
  const loading = ref(false);
  const busy = ref(false);
  const error = ref('');
  let generation = 0;
  let refreshing: number | undefined;
  const downloading = computed(() => info.value?.preparation.running === true);
  const running = computed(() => status.value?.running === true);
  const validRange = computed(
    () =>
      /^\d{4}-\d{2}-\d{2}$/.test(startDate.value) &&
      /^\d{4}-\d{2}-\d{2}$/.test(endDate.value) &&
      startDate.value < endDate.value &&
      endDate.value <= new Date().toISOString().slice(0, 10) &&
      new Date(endDate.value).getTime() - new Date(startDate.value).getTime() <= 3 * 366 * 86400000,
  );

  function client() {
    const id = bots.selectedBot;
    const { api } = useApi(useLoginInfo(id), id);
    const direct = bots.activeBot.canRunBacktest && !bots.activeBot.botState.nfi_live_management;
    return <T>(path: string, options?: FetchOptions<'json'>) => {
      const endpoint = direct
        ? ({
            '/info': '/research-info',
            '/prepare': '/research-prepare',
            ...(options?.method === 'POST' ? { '/backtest': '/research-backtest' } : {}),
          }[path] ?? path)
        : '/research' + path;
      return api<T>(endpoint, options);
    };
  }
  function message(value: unknown) {
    if (isApiError(value)) {
      if (value.data?.detail === 'research_data_required')
        return tr(
          'Download historical data for all selected pairs and dates before starting the backtest.',
        );
      if (value.data?.detail === 'research_service_auth_failed')
        return tr(
          'The research service credentials do not match. Recreate both services with the same configuration.',
        );
      if ([502, 503, 404].includes(value.status ?? 0))
        return tr('The research service is unavailable. Start the backtesting service and retry.');
    }
    return tr('The research request failed. Check the service logs and try again.');
  }
  function acceptStatus(data: BacktestStatus, filename?: string) {
    status.value = data;
    const results = data.backtest_result?.strategy;
    if (results) {
      result.value = results[strategy.value] ?? Object.values(results)[0];
      resultFilename.value =
        filename ?? data.backtest_result?.metadata?.[result.value?.strategy_name ?? '']?.filename;
    }
    if (data.status === 'error') error.value = data.status_msg;
  }
  async function refresh() {
    if (refreshing === generation || !bots.hasBots) return;
    const current = generation;
    refreshing = current;
    const api = client();
    try {
      const values = await Promise.all([
        api<ResearchInfo>('/info'),
        api<BacktestStatus>('/backtest'),
        api<BacktestHistoryEntry[]>('/backtest/history'),
      ]);
      if (current !== generation) return;
      info.value = values[0];
      acceptStatus(values[1]);
      history.value = values[2];
    } catch (value) {
      if (current === generation) error.value = message(value);
    } finally {
      if (refreshing === current) refreshing = undefined;
    }
  }
  async function load() {
    const current = ++generation;
    loading.value = true;
    error.value = '';
    try {
      const data = await client()<StrategyListResult>('/strategies');
      if (current !== generation) return;
      strategies.value = data.strategies;
      if (!strategies.value.includes(strategy.value)) strategy.value = strategies.value[0] ?? '';
      await refresh();
    } catch (value) {
      if (current === generation) error.value = message(value);
    } finally {
      if (current === generation) loading.value = false;
    }
  }
  async function action(work: (current: number) => Promise<void>) {
    if (busy.value) return;
    const current = generation;
    busy.value = true;
    error.value = '';
    try {
      await work(current);
    } catch (value) {
      if (current === generation) error.value = message(value);
    } finally {
      if (current === generation) busy.value = false;
    }
  }
  async function prepare() {
    if (!validRange.value || running.value || downloading.value) return;
    await action(async (current) => {
      const data = await client()<PreparationStatus>('/prepare', {
        method: 'POST',
        body: { start_date: startDate.value, end_date: endDate.value },
      });
      if (current === generation && info.value) info.value.preparation = data;
    });
  }
  async function start() {
    if (
      !validRange.value ||
      !strategy.value ||
      capital.value <= 0 ||
      running.value ||
      downloading.value
    )
      return;
    await action(async (current) => {
      const data = await client()<BacktestStatus>('/backtest', {
        method: 'POST',
        body: {
          strategy: strategy.value,
          timerange: startDate.value.replaceAll('-', '') + '-' + endDate.value.replaceAll('-', ''),
          timeframe: '5m',
          dry_run_wallet: capital.value,
          max_open_trades: info.value?.max_open_trades ?? 6,
          stake_amount: 'unlimited',
          enable_protections: protections.value,
          backtest_cache: 'none',
        },
      });
      if (current === generation) acceptStatus(data);
    });
  }
  async function stop() {
    await action(async (current) => {
      await client()('/backtest/abort');
      if (current === generation) await refresh();
    });
  }
  async function selectHistory(entry: BacktestHistoryEntry) {
    await action(async (current) => {
      const data = await client()<BacktestStatus>('/backtest/history/result', {
        query: { filename: entry.filename, strategy: entry.strategy },
      });
      if (current === generation) acceptStatus(data, entry.filename);
    });
  }
  const getStrategy = (name: string) =>
    client()<StrategyResult>('/strategy/' + encodeURIComponent(name));
  useIntervalFn(() => {
    if (running.value || downloading.value) void refresh();
  }, 3000);
  watch(
    () => bots.selectedBot,
    () => {
      ++generation;
      busy.value = false;
      info.value = undefined;
      strategies.value = [];
      status.value = undefined;
      result.value = undefined;
      resultFilename.value = undefined;
      history.value = [];
      if (bots.hasBots) void load();
    },
  );
  return {
    info,
    strategies,
    strategy,
    startDate,
    endDate,
    capital,
    protections,
    status,
    result,
    resultFilename,
    history,
    loading,
    busy,
    error,
    downloading,
    running,
    validRange,
    load,
    refresh,
    prepare,
    start,
    stop,
    selectHistory,
    getStrategy,
  };
});
