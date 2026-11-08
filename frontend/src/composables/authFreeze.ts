import { computed, onScopeDispose, reactive, ref, toValue, type MaybeRefOrGetter } from 'vue';
import { FetchError } from 'ofetch';
import { tr } from '@/i18n';

const frozenUntil = ref<Record<string, number>>({});

function targetKey(value: string, scope: string) {
  try {
    const url = new URL(value, window.location.origin);
    const path = url.pathname.replace(/\/api\/v1(?:\/.*)?$/, '').replace(/\/+$/, '');
    return `${url.origin}${path}:${scope}`;
  } catch {
    return `${value}:${scope}`;
  }
}

export function recordAuthFreeze(
  target: string,
  data: unknown,
  retryAfter?: string | null,
  scope = 'password',
) {
  if (
    !data ||
    typeof data !== 'object' ||
    !('detail' in data) ||
    data.detail !== 'account_rate_limited'
  )
    return false;
  const seconds = Number(
    ('retry_after' in data ? data.retry_after : undefined) ?? retryAfter ?? 300,
  );
  const safeSeconds = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 300;
  const key = targetKey(target, scope);
  frozenUntil.value[key] = Math.max(frozenUntil.value[key] ?? 0, Date.now() + safeSeconds * 1000);
  return true;
}

export function useAuthFreeze(target: MaybeRefOrGetter<string>, scope = 'password') {
  const now = ref(Date.now());
  const timer = setInterval(() => {
    now.value = Date.now();
  }, 1000);
  onScopeDispose(() => clearInterval(timer));
  const remaining = computed(() =>
    Math.max(
      0,
      Math.ceil(
        ((frozenUntil.value[targetKey(toValue(target), scope)] ?? 0) -
          Math.max(now.value, Date.now())) /
          1000,
      ),
    ),
  );
  function capture(error: unknown) {
    return (
      error instanceof FetchError &&
      error.status === 429 &&
      recordAuthFreeze(
        toValue(target),
        error.data,
        error.response?.headers.get('Retry-After'),
        scope,
      )
    );
  }
  function restore(seconds: number) {
    if (seconds > 0)
      recordAuthFreeze(
        toValue(target),
        { detail: 'account_rate_limited', retry_after: seconds },
        null,
        scope,
      );
  }
  return reactive({
    remaining,
    message: computed(() =>
      tr('Password verification is temporarily frozen. Try again in {0} seconds.', {
        0: remaining.value,
      }),
    ),
    capture,
    restore,
  });
}
