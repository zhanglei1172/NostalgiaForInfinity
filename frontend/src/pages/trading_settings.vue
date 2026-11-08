<script setup lang="ts">
import { language, tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
import type { LiveBalance, LiveSettings } from '@/types/live';

const bots = useBotStore();
const freeze = useAuthFreeze(() => bots.activeBot?.getLoginInfo().apiUrl ?? window.location.origin);
const { confirm } = useConfirmBox();
const info = ref<LiveSettings>();
const balance = ref<LiveBalance>();
const label = ref('OKX');
const capital = ref<number>();
const key = ref('');
const secret = ref('');
const passphrase = ref('');
const password = ref('');
const busy = ref(false);
const loading = ref(false);
const unsupported = ref(false);
const pending = ref(false);
const error = ref('');
const notice = ref('');
let generation = 0;
const phase = computed(() =>
  tr(
    {
      setup: 'Awaiting account configuration',
      loading: 'Loading the live service',
      applying: 'Applying account settings',
      ready: 'Live service ready',
      error: 'Live service initialization failed',
    }[info.value?.phase ?? 'setup'],
  ),
);
const credentialsReady = computed(
  () => info.value?.credentials_configured || (key.value && secret.value && passphrase.value),
);
const valid = computed(
  () =>
    credentialsReady.value &&
    label.value.trim() &&
    Number.isFinite(capital.value) &&
    (capital.value ?? 0) >= 100 &&
    password.value.length > 0,
);
function api() {
  const id = bots.selectedBot;
  return useApi(useLoginInfo(id), id).api;
}
function clearSecrets() {
  key.value = '';
  secret.value = '';
  passphrase.value = '';
  password.value = '';
}
function credentials() {
  return {
    api_key: key.value || undefined,
    api_secret: secret.value || undefined,
    passphrase: passphrase.value || undefined,
  };
}
function failure(value: unknown) {
  if (freeze.capture(value)) return '';
  const messages: Record<string, string> = {
    live_origin_rejected:
      "The request origin was rejected. Open this bot's own Web address or check the reverse-proxy forwarding settings.",
    live_connection_failed:
      'Connection failed. Check the OKX credentials, read permission, IP allowlist and network.',
    live_credentials_required:
      'Enter the API Key, Secret and Passphrase for the first configuration.',
    live_stop_required: 'Stop the bot before changing the trading account settings.',
    live_revision_conflict:
      'The account settings changed in another session. Reload before saving.',
    live_insufficient_balance:
      'Available USDT is below the budget. Transfer funds to the OKX trading account or lower the budget.',
    live_account_has_history:
      'This database contains trades for another OKX account. Use a separate deployment for the new account.',
    live_capital_has_positions:
      'Close positions and resolve open orders before changing the initial budget.',
    live_database_unavailable:
      'The trading database is temporarily unavailable. Retry after the service finishes loading.',
    account_guard_unavailable:
      'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
    account_incorrect_password: 'The current password is incorrect.',
    account_rate_limited: 'Too many incorrect attempts. Try again in 5 minutes.',
    account_invalid_request: 'Check the account fields and try again.',
  };
  if (isApiError(value) && typeof value.data?.detail === 'string')
    return tr(
      messages[value.data.detail] ??
        'The account request failed. Refresh the status and try again.',
    );
  return tr('The account request failed. Refresh the status and try again.');
}
async function load(reset = false) {
  if (!bots.hasBots) return;
  const current = generation;
  if (reset) {
    clearSecrets();
    balance.value = undefined;
    loading.value = true;
    error.value = '';
  }
  try {
    const data = await api()<LiveSettings>('/live-settings');
    if (current !== generation) return;
    if (typeof data.configured !== 'boolean') {
      unsupported.value = true;
      return;
    }
    info.value = data;
    unsupported.value = false;
    if (reset) {
      label.value = data.account_label;
      capital.value = data.available_capital ?? undefined;
    }
    if (pending.value && data.phase === 'ready' && data.runtime_revision === data.revision) {
      pending.value = false;
      notice.value = tr(
        'Account settings applied. The bot remains stopped; review the account before starting trading.',
      );
      void bots.activeBot.getState();
    } else if (data.phase === 'error') pending.value = false;
  } catch (value) {
    if (current !== generation) return;
    if (isApiError(value) && value.status === 404) unsupported.value = true;
    else if (!pending.value) error.value = failure(value);
  } finally {
    if (current === generation) loading.value = false;
  }
}
async function check() {
  if (busy.value || !credentialsReady.value) return;
  const current = generation;
  busy.value = true;
  error.value = '';
  notice.value = '';
  balance.value = undefined;
  try {
    const data = await api()<LiveBalance>('/live-settings/check', {
      method: 'POST',
      body: credentials(),
      timeout: 60000,
    });
    if (current === generation) balance.value = data;
  } catch (value) {
    if (current === generation) error.value = failure(value);
  } finally {
    if (current === generation) busy.value = false;
  }
}
async function save() {
  if (busy.value || !valid.value || !info.value || pending.value || freeze.remaining) return;
  const current = generation;
  if (
    !(await confirm({
      title: tr('Apply trading account settings'),
      message: tr(
        'Validate the account and apply these settings? The service will reload in stopped state. Existing trade records are preserved.',
      ),
    }))
  )
    return;
  if (current !== generation) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const result = await api()<{ revision: number; balance: LiveBalance }>('/live-settings', {
      method: 'PUT',
      timeout: 60000,
      body: {
        ...credentials(),
        revision: info.value.revision,
        account_label: label.value,
        available_capital: capital.value,
        current_password: password.value,
      },
    });
    if (current !== generation) return;
    balance.value = result.balance;
    pending.value = true;
    notice.value = tr('Saved. Applying settings; the bot will remain stopped.');
    clearSecrets();
    await load();
  } catch (value) {
    if (current === generation) error.value = failure(value);
  } finally {
    if (current === generation) {
      password.value = '';
      busy.value = false;
    }
  }
}
async function reloadWorker() {
  if (!password.value || busy.value || freeze.remaining) return;
  const current = generation;
  busy.value = true;
  error.value = '';
  try {
    await api()('/live-settings/reload', {
      method: 'POST',
      body: { current_password: password.value },
    });
    if (current === generation) {
      pending.value = true;
      notice.value = tr('Reload requested. The bot will remain stopped.');
    }
  } catch (value) {
    if (current === generation) error.value = failure(value);
  } finally {
    if (current === generation) {
      busy.value = false;
      password.value = '';
    }
  }
}
watch(
  () => bots.selectedBot,
  () => {
    ++generation;
    clearSecrets();
    info.value = undefined;
    balance.value = undefined;
    busy.value = false;
    pending.value = false;
    notice.value = '';
    unsupported.value = false;
    void load(true);
  },
);
useIntervalFn(() => {
  if (pending.value || info.value?.phase === 'loading' || info.value?.phase === 'applying')
    void load();
}, 2000);
onMounted(() => load(true));
onBeforeUnmount(() => {
  ++generation;
  clearSecrets();
});
</script>
<template>
  <div class="workspace-page trading-settings-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">OKX · SPOT</p>
        <h1>{{ tr('Trading account') }}</h1>
        <p>
          {{ tr('Manage exchange credentials and the live trading budget in the Web interface.') }}
        </p>
      </div>
      <UButton
        color="neutral"
        icon="i-mdi-refresh"
        :loading="loading"
        :disabled="busy || pending"
        @click="load(true)"
        >{{ tr('Reload saved account settings') }}</UButton
      >
    </div>
    <UAlert v-if="error" role="alert" color="error" :title="error" class="mb-5" />
    <UAlert v-if="notice" role="status" color="info" :title="notice" class="mb-5" />
    <UAlert
      v-if="unsupported"
      :title="
        tr(
          'This bot uses public paper-trading data. Connect to the live management service to configure an exchange account.',
        )
      "
      color="info"
    />
    <p v-else-if="loading && !info">{{ tr('Loading…') }}</p>
    <template v-else-if="info">
      <section class="workspace-panel p-5 mb-5">
        <div class="flex flex-wrap gap-3 items-center">
          <h2>{{ phase }}</h2>
          <UBadge color="neutral">{{ tr('Live trading') }}</UBadge>
        </div>
        <p class="muted text-sm mt-3">
          {{
            tr('Saved revision: {saved} · Loaded revision: {loaded}', {
              saved: info.revision,
              loaded: info.runtime_revision,
            })
          }}
        </p>
        <p v-if="info.account_uid" class="text-sm mt-2">
          {{ tr('OKX account UID') }}: {{ info.account_uid }}
        </p>
        <p v-if="info.phase === 'error'" class="text-sm mt-3">
          {{
            tr(
              'The live worker could not initialize. Review the credentials, permissions and network, then reload the saved configuration.',
            )
          }}
        </p>
        <p class="muted text-sm mt-3">
          {{
            tr(
              'Saving never starts trading. Change settings with the bot stopped; open positions prevent budget changes. Use the trading controls to start after review.',
            )
          }}
        </p>
      </section>
      <form class="workspace-panel p-5 sm:p-6" @submit.prevent="save">
        <h2 class="mb-5">{{ tr('Exchange credentials and budget') }}</h2>
        <div class="account-settings-grid">
          <UFormField :label="tr('Account label')"
            ><UInput
              v-model="label"
              class="w-full"
              :maxlength="60"
              :disabled="busy || pending"
              required
          /></UFormField>
          <UFormField
            :label="tr('Initial trading budget (USDT)')"
            :help="
              tr(
                'At least 100 USDT, subject to actual order minimums. Realized profit or loss changes the available budget; this is not a maximum-loss limit.',
              )
            "
          >
            <UInputNumber
              v-model="capital"
              :min="100"
              :max="1000000000"
              :increment="false"
              :decrement="false"
              class="w-full"
              :disabled="busy || pending"
            />
          </UFormField>
          <UFormField
            :label="tr('OKX API Key')"
            :help="
              info.credentials_configured
                ? tr('Configured. Leave blank to keep the saved value.')
                : tr('Required for the first configuration.')
            "
          >
            <PasswordInput
              v-model="key"
              autocomplete="off"
              class="w-full"
              :disabled="busy || pending"
            />
          </UFormField>
          <UFormField
            :label="tr('OKX API Secret')"
            :help="
              info.credentials_configured
                ? tr('Configured. Leave blank to keep the saved value.')
                : tr('Required for the first configuration.')
            "
          >
            <PasswordInput
              v-model="secret"
              autocomplete="off"
              class="w-full"
              :disabled="busy || pending"
            />
          </UFormField>
          <UFormField
            :label="tr('OKX API Passphrase')"
            :help="
              tr('The passphrase set when creating the OKX API key, not your OKX login password.')
            "
          >
            <PasswordInput
              v-model="passphrase"
              autocomplete="off"
              class="w-full"
              :disabled="busy || pending"
            />
          </UFormField>
          <UFormField
            :label="tr('Current administrator password')"
            :help="tr('Required to save or reload account settings.')"
          >
            <PasswordInput
              v-model="password"
              autocomplete="current-password"
              class="w-full"
              :disabled="busy || pending"
            />
          </UFormField>
        </div>
        <p class="muted text-sm mt-5">
          {{
            tr(
              'Saved exchange secrets are never returned to the browser. They are stored in private files on the server, outside Docker commands and environment variables.',
            )
          }}
        </p>
        <div class="flex flex-wrap gap-3 mt-6">
          <UButton
            type="button"
            color="neutral"
            :disabled="busy || pending || !credentialsReady"
            :loading="busy"
            @click="check"
            >{{ tr('Test connection and read balance') }}</UButton
          >
          <UButton
            type="submit"
            :disabled="busy || pending || !valid || !!freeze.remaining"
            :loading="busy"
            >{{ tr('Save and apply in stopped state') }}</UButton
          >
          <UButton
            v-if="info.configured"
            type="button"
            color="neutral"
            variant="outline"
            :disabled="busy || pending || !password || !!freeze.remaining"
            @click="reloadWorker"
            >{{ tr('Reload saved live configuration') }}</UButton
          >
        </div>
      </form>
      <section v-if="balance" class="workspace-panel p-5 mt-5" aria-live="polite">
        <h2>{{ tr('OKX trading-account balance') }}</h2>
        <p class="muted text-sm mt-2">
          {{ tr('Read-only exchange values. Transfer funds between OKX accounts in OKX itself.') }}
        </p>
        <dl class="balance-grid mt-5">
          <div>
            <dt class="muted text-sm">{{ tr('Available USDT') }}</dt>
            <dd>{{ balance.free.toLocaleString() }}</dd>
          </div>
          <div>
            <dt class="muted text-sm">{{ tr('In use USDT') }}</dt>
            <dd>{{ balance.used.toLocaleString() }}</dd>
          </div>
          <div>
            <dt class="muted text-sm">{{ tr('Total USDT') }}</dt>
            <dd>{{ balance.total.toLocaleString() }}</dd>
          </div>
        </dl>
        <p class="muted text-xs mt-4">
          UID: {{ balance.uid }} · {{ new Date(balance.checked_at).toLocaleString(language) }}
        </p>
        <p class="text-sm mt-3">
          {{
            tr(
              'Successful balance access confirms read permission only; verify trading permission in OKX separately.',
            )
          }}
        </p>
      </section>
    </template>
  </div>
</template>
<style scoped>
.trading-settings-page {
  max-width: 1100px;
}
.account-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.balance-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 640px) {
  .account-settings-grid,
  .balance-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
