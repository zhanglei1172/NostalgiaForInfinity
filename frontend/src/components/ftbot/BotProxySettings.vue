<script setup lang="ts">
import { tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
import type { ProxyCheck, ProxyDraft, ProxySettings } from '@/types/proxy';

const bots = useBotStore();
const freeze = useAuthFreeze(() => bots.activeBot?.getLoginInfo().apiUrl ?? window.location.origin);
const { confirm } = useConfirmBox();
const settings = ref<ProxySettings>();
const draft = ref<ProxyDraft>();
const username = ref('');
const proxyPassword = ref('');
const password = ref('');
const busy = ref(false);
const loading = ref(false);
const unsupported = ref(false);
const error = ref('');
const notice = ref('');
const check = ref<ProxyCheck>();
let generation = 0;
const apiFor = (id: string) => useApi(useLoginInfo(id), id).api;
const rulesOf = (data: ProxySettings): ProxyDraft => ({
  enabled: data.settings.enabled,
  protocol: data.settings.protocol,
  host: data.settings.host,
  port: data.settings.port,
  auth_enabled: data.settings.auth_enabled,
});
const protocols = computed(() => [
  { label: tr('SOCKS5 with proxy DNS (recommended)'), value: 'socks5h' },
  { label: tr('SOCKS5 with local DNS'), value: 'socks5' },
  { label: tr('HTTP proxy'), value: 'http' },
  { label: tr('HTTPS proxy'), value: 'https' },
]);
const changed = computed(
  () =>
    settings.value &&
    draft.value &&
    (JSON.stringify(draft.value) !== JSON.stringify(rulesOf(settings.value)) ||
      !!username.value ||
      !!proxyPassword.value),
);
const valid = computed(
  () =>
    draft.value &&
    Number.isInteger(draft.value.port) &&
    draft.value.port >= 1 &&
    draft.value.port <= 65535 &&
    (!draft.value.enabled || !!draft.value.host.trim()) &&
    (!draft.value.auth_enabled ||
      ((username.value || settings.value?.settings.username_configured) &&
        (proxyPassword.value || settings.value?.settings.password_configured))),
);
const applyPending = computed(
  () =>
    settings.value &&
    (settings.value.pending_changes ||
      settings.value.runtime_revision !== settings.value.active_revision),
);
const messages: Record<string, string> = {
  proxy_origin_rejected:
    "The request origin was rejected. Open this bot's own Web address or check the reverse-proxy forwarding settings.",
  account_incorrect_password: 'The current password is incorrect.',
  account_rate_limited: 'Too many incorrect attempts. Try again in 5 minutes.',
  account_guard_unavailable:
    'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
  account_invalid_request: 'Check the proxy fields and try again.',
  proxy_invalid_settings:
    'Enter a proxy host without a URL scheme, a valid port and any required credentials.',
  proxy_revision_conflict: 'Proxy settings changed in another session. Reload before continuing.',
  proxy_storage_unavailable: 'Proxy settings storage is unavailable. Check file permissions.',
  proxy_stop_required:
    'Stop the bot before applying proxy settings. Drafts and connection tests remain available.',
  proxy_positions_open: 'Close open positions and orders before applying proxy settings.',
  proxy_test_rate_limited: 'Wait 30 seconds before testing the connection again.',
  proxy_auth_failed: 'The proxy or exchange rejected authentication.',
  proxy_timeout: 'The connection timed out.',
  proxy_exchange_limited: 'OKX limited the public request. Try again later.',
  proxy_dependency_missing: 'Proxy dependencies are missing. Update the NFI image.',
  proxy_connection_failed:
    'Connection failed. Check the proxy address, authentication and network access.',
};
const message = (code: string) =>
  tr(messages[code] ?? 'Unable to update proxy settings. Refresh and try again.');
function failure(value: unknown) {
  if (freeze.capture(value)) return '';
  return message(
    isApiError(value) && typeof value.data?.detail === 'string' ? value.data.detail : '',
  );
}
function accept(data: ProxySettings) {
  settings.value = data;
  draft.value = rulesOf(data);
  username.value = proxyPassword.value = password.value = '';
}
async function load() {
  const sequence = ++generation;
  const id = bots.selectedBot;
  settings.value = draft.value = undefined;
  username.value = proxyPassword.value = password.value = error.value = notice.value = '';
  check.value = undefined;
  unsupported.value = false;
  busy.value = false;
  loading.value = true;
  try {
    if (!bots.hasBots) return;
    const data = await apiFor(id)<ProxySettings>('/proxy-settings');
    if (sequence !== generation) return;
    if (typeof data.settings?.enabled !== 'boolean') unsupported.value = true;
    else accept(data);
  } catch (value) {
    if (sequence !== generation) return;
    if (isApiError(value) && value.status === 404) unsupported.value = true;
    else error.value = failure(value);
  } finally {
    if (sequence === generation) loading.value = false;
  }
}
async function submit(action: 'save' | 'check' | 'apply') {
  if (
    !settings.value ||
    !draft.value ||
    !password.value ||
    busy.value ||
    freeze.remaining ||
    !valid.value
  )
    return;
  if (action === 'save' && !changed.value) return;
  if (action === 'apply' && (changed.value || !settings.value.can_apply || !applyPending.value))
    return;
  const sequence = generation;
  const id = bots.selectedBot;
  if (
    action === 'apply' &&
    !(await confirm({
      title: tr('Apply exchange proxy settings'),
      message: tr(
        'The exchange connection will reload and the bot will remain stopped. Start it manually after checking the connection. Apply the saved settings?',
      ),
    }))
  )
    return;
  if (sequence !== generation) return;
  busy.value = true;
  error.value = notice.value = '';
  check.value = undefined;
  try {
    const body = {
      revision: settings.value.revision,
      current_password: password.value,
      ...(action === 'apply'
        ? {}
        : { ...draft.value, username: username.value, password: proxyPassword.value }),
    };
    if (action === 'check') {
      const result = await apiFor(id)<ProxyCheck>('/proxy-settings/check', {
        method: 'POST',
        body,
      });
      if (sequence !== generation) return;
      check.value = result;
    } else {
      const data = await apiFor(id)<ProxySettings>(
        action === 'apply' ? '/proxy-settings/apply' : '/proxy-settings',
        {
          method: action === 'apply' ? 'POST' : 'PUT',
          body,
        },
      );
      if (sequence !== generation) return;
      accept(data);
      notice.value =
        action === 'save'
          ? tr('Proxy draft saved. Apply it to change the exchange connection.')
          : tr(
              'Saved connection selected. Wait for the service to reload, then refresh this panel and start the bot manually.',
            );
    }
  } catch (value) {
    if (sequence === generation) error.value = failure(value);
  } finally {
    if (sequence === generation) {
      busy.value = false;
      password.value = '';
    }
  }
}
const checkNames = computed(() => ({
  rest_sync: tr('REST account and order requests'),
  rest_async: tr('REST candle requests'),
  websocket: tr('WebSocket candle subscription'),
}));
watch(() => bots.selectedBot, load, { immediate: true });
onBeforeUnmount(() => {
  ++generation;
  password.value = username.value = proxyPassword.value = '';
});
</script>

<template>
  <section class="workspace-panel max-w-4xl p-6 mb-6" aria-labelledby="proxy-settings-heading">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <h2 id="proxy-settings-heading" class="section-title">{{ tr('Exchange proxy') }}</h2>
      <UButton
        color="neutral"
        icon="i-mdi-refresh"
        :loading="loading"
        :disabled="busy"
        @click="load"
        >{{ tr('Reload proxy settings') }}</UButton
      >
    </div>
    <UAlert v-if="error" role="alert" color="error" :title="error" class="mb-4" />
    <UAlert v-if="notice" role="status" color="info" :title="notice" class="mb-4" />
    <p v-if="loading" class="muted">{{ tr('Loading…') }}</p>
    <p v-else-if="unsupported" class="muted">
      {{ tr('This bot does not support Web proxy settings. Update its NFI image.') }}
    </p>
    <form v-else-if="settings && draft" class="space-y-5" @submit.prevent="submit('save')">
      <div class="flex flex-wrap gap-2">
        <UBadge :color="settings.role === 'live' ? 'warning' : 'neutral'">{{
          settings.role === 'live' ? tr('Live trading') : tr('Paper trading')
        }}</UBadge>
        <UBadge color="neutral">{{
          settings.runtime_enabled === null
            ? tr('Exchange service not loaded')
            : settings.runtime_enabled
              ? tr('Current connection: proxy')
              : tr('Current connection: direct')
        }}</UBadge>
        <UBadge v-if="applyPending" color="warning">{{ tr('Connection changes pending') }}</UBadge>
      </div>
      <USwitch
        v-model="draft.enabled"
        :label="tr('Use a proxy to connect to the exchange')"
        :disabled="busy"
      />
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Off uses a direct connection. Saved drafts do not affect the running bot. Settings are private and independent for each paper or live bot.',
          )
        }}
      </p>
      <fieldset :disabled="busy || !draft.enabled" class="space-y-4">
        <div class="grid sm:grid-cols-2 gap-4">
          <UFormField :label="tr('Proxy protocol')"
            ><USelect v-model="draft.protocol" :items="protocols" class="w-full"
          /></UFormField>
          <UFormField :label="tr('Proxy port')"
            ><UInputNumber v-model="draft.port" :min="1" :max="65535" :step="1" class="w-full"
          /></UFormField>
        </div>
        <UFormField
          :label="tr('Proxy host')"
          :help="
            tr('Enter only a hostname or IP, for example host.docker.internal or 192.168.1.10.')
          "
          ><UInput v-model="draft.host" autocomplete="off" :maxlength="253" class="w-full"
        /></UFormField>
        <USwitch
          v-model="draft.auth_enabled"
          :label="tr('Proxy requires a username and password')"
        />
        <div v-if="draft.auth_enabled" class="grid sm:grid-cols-2 gap-4">
          <UFormField :label="tr('Proxy username')"
            ><PasswordInput v-model="username" autocomplete="off" :maxlength="253" class="w-full"
          /></UFormField>
          <UFormField :label="tr('Proxy password')"
            ><PasswordInput
              v-model="proxyPassword"
              autocomplete="new-password"
              :maxlength="253"
              class="w-full"
          /></UFormField>
        </div>
        <p
          v-if="settings.settings.username_configured || settings.settings.password_configured"
          class="muted text-sm"
        >
          {{
            tr(
              'Proxy credentials are saved privately and are not returned. Leave blank to keep them; turn authentication off and save to clear them.',
            )
          }}
        </p>
      </fieldset>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Inside Docker, 127.0.0.1 is this container. For a host proxy use host.docker.internal and allow connections from the Docker network; a host proxy listening only on 127.0.0.1 is not reachable.',
          )
        }}
      </p>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            "The proxy covers this bot's exchange REST and WebSocket connections, including live account checks. Bark, browser access and the research service keep their own connections.",
          )
        }}
      </p>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Connection tests use public OKX time and BTC candles without account keys or orders. They test this form and do not save or apply it. A successful test does not guarantee long-term stability.',
          )
        }}
      </p>
      <UAlert
        v-if="settings.apply_block_reason"
        color="warning"
        :title="message(settings.apply_block_reason)"
      />
      <UFormField :label="tr('Administrator password for proxy settings')" class="max-w-md"
        ><PasswordInput
          v-model="password"
          autocomplete="current-password"
          :disabled="busy"
          :maxlength="1024"
          class="w-full"
      /></UFormField>
      <div class="flex flex-wrap gap-3">
        <UButton
          type="submit"
          :disabled="!changed || !valid || !password || busy || !!freeze.remaining"
          :loading="busy"
          >{{ tr('Save proxy draft') }}</UButton
        >
        <UButton
          type="button"
          color="neutral"
          :disabled="!valid || !password || busy || !!freeze.remaining"
          @click="submit('check')"
          >{{ tr('Test exchange connection') }}</UButton
        >
        <UButton
          type="button"
          color="warning"
          :disabled="
            changed ||
            !applyPending ||
            !settings.can_apply ||
            !password ||
            busy ||
            !!freeze.remaining
          "
          @click="submit('apply')"
          >{{ tr('Apply saved connection') }}</UButton
        >
      </div>
      <ul v-if="check" class="space-y-2 text-sm" aria-live="polite">
        <li v-for="(item, key) in check.checks" :key="key" class="break-words">
          {{ checkNames[key] }} · {{ item.success ? tr('Connected') : tr('Connection failed')
          }}<span v-if="item.latency_ms !== undefined"> · {{ item.latency_ms }} ms</span
          ><span v-if="item.error"> · {{ message(item.error) }}</span>
        </li>
      </ul>
    </form>
  </section>
</template>
