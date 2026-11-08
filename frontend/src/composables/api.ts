import type { $Fetch } from 'ofetch';
import { FetchError, ofetch } from 'ofetch';
import { recordAuthFreeze } from './authFreeze';

type UserServiceType = ReturnType<typeof useLoginInfo>;

/** Error body shapes returned by the freqtrade API. */
export interface ApiErrorBody {
  detail?: string;
  error?: string;
  retry_after?: number;
}

/** Type guard for errors thrown by the API client (non-2xx responses, network errors, timeouts). */
export function isApiError(error: unknown): error is FetchError<ApiErrorBody> {
  return error instanceof FetchError;
}

/** True if the error was caused by the request timeout. */
export function isTimeoutError(error: unknown): boolean {
  return isApiError(error) && (error.cause as Error | undefined)?.name === 'TimeoutError';
}

export function useApi(userService: UserServiceType, botId: string): { api: $Fetch } {
  function markBotOffline(loggedOut = false) {
    const botStore = useBotStore();
    const subStore = botStore.botStores[botId];
    if (subStore) {
      subStore.setIsBotOnline(false);
      if (loggedOut) {
        subStore.isBotLoggedIn = false;
      }
    }
  }

  const api = ofetch.create({
    baseURL: userService.baseUrl.value,
    timeout: 20000,
    credentials: 'include',
    // Retry exactly once, and only after a 401 - the retried request runs through
    // onRequest again and picks up the refreshed access token.
    retry: 1,
    retryDelay: 0,
    retryStatusCodes: [401],
    onRequest({ options }) {
      const token = userService.accessToken.value;
      if (token) {
        options.headers.set('Authorization', `Bearer ${token}`);
      }
    },
    onRequestError() {
      // fetch itself failed (network error, CORS, DNS, ...) - no response available.
      console.log('Bot not running...');
      markBotOffline();
    },
    async onResponseError({ response, options }) {
      if (response.status === 429) {
        recordAuthFreeze(response.url, response._data, response.headers.get('Retry-After'));
      }
      if (response.status === 401) {
        try {
          await userService.refreshToken();
        } catch {
          console.log('No new token received');
          markBotOffline(true);
          // Refresh failed - don't retry, let the original 401 propagate to the caller.
          options.retry = 0;
        }
      } else if (response.status === 500) {
        console.log('Bot not running...');
        markBotOffline();
      }
    },
  });

  return {
    api,
  };
}
