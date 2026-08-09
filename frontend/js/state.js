export const state = {
  sources: [],
  currentSource: 'combined',
  timeRange: 'all',
  mode: 'total',
  cachedHistory: null,
  cachedLatestOverview: null,
  cachedModelData: null,
  lastFetchTime: 0,
  lastHistoryCycleTs: null,
  lastHistoryFetchTime: 0,
  latestObservedCycleTs: null,
  latestCompleteTimestamp: null,
  offline: !navigator.onLine,
  sortColumn: 'total',
  sortDirection: 'desc',
};

export const HISTORY_STALE_MS = 15 * 60 * 1000;

export const RANGE_LABELS = {
  '1h': ' (Last Hour)',
  '6h': ' (Last 6 Hours)',
  '1d': ' (Last 24 Hours)',
  '1w': ' (Last Week)',
  '1m': ' (Last Month)',
  '3m': ' (Last 3 Months)',
  'all': ' (All Time)'
};
