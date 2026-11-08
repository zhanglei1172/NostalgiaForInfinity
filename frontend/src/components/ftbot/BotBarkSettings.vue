<script setup lang="ts">
import { tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
import type { BarkRules, BarkSettings } from '@/types/bark';

const bots = useBotStore();
const freeze = useAuthFreeze(() => bots.activeBot?.getLoginInfo().apiUrl ?? window.location.origin);
const settings = ref<BarkSettings>();
const draft = ref<BarkRules>();
const destination = ref('');
const clearDestination = ref(false);
const password = ref('');
const loading = ref(false);
const busy = ref(false);
const unsupported = ref(false);
const error = ref('');
const notice = ref('');
let generation = 0;
const apiFor = (id: string) => useApi(useLoginInfo(id), id).api;
const rulesOf = (data: BarkSettings): BarkRules => ({
  enabled: data.enabled,
  profit_enabled: data.profit_enabled,
  profit_threshold_pct: data.profit_threshold_pct,
  loss_enabled: data.loss_enabled,
  loss_threshold_pct: data.loss_threshold_pct,
  state_enabled: data.state_enabled,
  cooldown_minutes: data.cooldown_minutes,
});
const changed = computed(
  () =>
    settings.value &&
    draft.value &&
    (JSON.stringify(draft.value) !== JSON.stringify(rulesOf(settings.value)) ||
      !!destination.value.trim() ||
      clearDestination.value),
);
const valid = computed(
  () =>
    draft.value &&
    Number.isFinite(draft.value.profit_threshold_pct) &&
    draft.value.profit_threshold_pct >= 0.01 &&
    draft.value.profit_threshold_pct <= 100000 &&
    Number.isFinite(draft.value.loss_threshold_pct) &&
    draft.value.loss_threshold_pct >= 0.01 &&
    draft.value.loss_threshold_pct <= 100 &&
    Number.isInteger(draft.value.cooldown_minutes) &&
    draft.value.cooldown_minutes >= 5 &&
    draft.value.cooldown_minutes <= 1440 &&
    (!draft.value.enabled ||
      ((destination.value.trim() ||
        (settings.value?.destination_configured && !clearDestination.value)) &&
        (draft.value.profit_enabled || draft.value.loss_enabled || draft.value.state_enabled))),
);
function message(code: string) {
  const messages: Record<string, string> = {
    bark_origin_rejected:
      "The request origin was rejected. Open this bot's own Web address or check the reverse-proxy forwarding settings.",
    account_guard_unavailable:
      'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
    account_incorrect_password: 'The current password is incorrect.',
    account_rate_limited: 'Too many incorrect attempts. Try again in 5 minutes.',
    bark_revision_conflict: 'Bark settings changed in another session. Reload before continuing.',
    bark_storage_unavailable:
      'Bark settings could not be read or saved. Check storage permissions.',
    bark_invalid_destination:
      'Enter a full Bark push URL, including its device key, without query parameters.',
    bark_missing_rule_or_destination:
      'Save a Bark destination and select at least one notification event.',
    bark_delivery_failed:
      'Bark delivery failed. Check the saved address, device key and server connection.',
    bark_test_rate_limited: 'Wait one minute before sending another test notification.',
    bark_bot_not_ready: 'Waiting for the trading account to finish initialization.',
    bark_metrics_unavailable:
      'Profit data is unavailable. Monitoring will retry without sending a threshold alert.',
    account_invalid_request: 'Check the Bark address, thresholds and cooldown, then try again.',
  };
  return tr(messages[code] ?? 'Unable to update Bark notifications. Refresh and try again.');
}
function failure(value: unknown) {
  if (freeze.capture(value)) return '';
  return message(
    isApiError(value) && typeof value.data?.detail === 'string' ? value.data.detail : '',
  );
}
function accept(data: BarkSettings) {
  settings.value = data;
  draft.value = rulesOf(data);
}
async function load() {
  const sequence = ++generation;
  const id = bots.selectedBot;
  password.value = destination.value = error.value = notice.value = '';
  clearDestination.value = false;
  settings.value = undefined;
  draft.value = undefined;
  unsupported.value = false;
  loading.value = true;
  busy.value = false;
  try {
    if (!bots.hasBots) return;
    const data = await apiFor(id)<BarkSettings>('/bark-settings');
    if (sequence !== generation) return;
    if (typeof data.destination_configured !== 'boolean') unsupported.value = true;
    else accept(data);
  } catch (value) {
    if (sequence !== generation) return;
    if (isApiError(value) && value.status === 404) unsupported.value = true;
    else error.value = failure(value);
  } finally {
    if (sequence === generation) loading.value = false;
  }
}
async function submit(test = false) {
  if (!settings.value || !draft.value || !password.value || busy.value || freeze.remaining) return;
  if (
    test ? changed.value || !settings.value.destination_configured : !changed.value || !valid.value
  )
    return;
  const sequence = generation;
  const id = bots.selectedBot;
  busy.value = true;
  error.value = notice.value = '';
  try {
    const data = await apiFor(id)<BarkSettings>(test ? '/bark-settings/test' : '/bark-settings', {
      method: test ? 'POST' : 'PUT',
      body: {
        revision: settings.value.revision,
        current_password: password.value,
        ...(test
          ? {}
          : {
              ...draft.value,
              destination: destination.value,
              clear_destination: clearDestination.value,
            }),
      },
    });
    if (sequence !== generation) return;
    accept(data);
    destination.value = '';
    clearDestination.value = false;
    notice.value = test
      ? tr('Test notification accepted by Bark. Check your device.')
      : tr('Bark notification settings saved.');
  } catch (value) {
    if (sequence === generation) error.value = failure(value);
  } finally {
    if (sequence === generation) {
      busy.value = false;
      password.value = '';
      destination.value = '';
    }
  }
}
const eventLabel = (event: string) =>
  ({
    profit: tr('Profit target reached'),
    loss: tr('Loss threshold reached'),
    state: tr('Bot state changed'),
    test: tr('Test notification'),
  })[event] ?? event;
watch(() => bots.selectedBot, load, { immediate: true });
onBeforeUnmount(() => {
  ++generation;
  password.value = destination.value = '';
});
</script>

<template>
  <section class="workspace-panel max-w-4xl p-6 mb-6" aria-labelledby="bark-settings-heading">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <h2 id="bark-settings-heading" class="section-title">{{ tr('Bark notifications') }}</h2>
      <UButton
        color="neutral"
        icon="i-mdi-refresh"
        :loading="loading"
        :disabled="busy"
        @click="load"
        >{{ tr('Reload Bark settings') }}</UButton
      >
    </div>
    <UAlert v-if="error" role="alert" color="error" :title="error" class="mb-4" />
    <UAlert v-if="notice" role="status" color="info" :title="notice" class="mb-4" />
    <p v-if="loading" class="muted">{{ tr('Loading…') }}</p>
    <p v-else-if="unsupported" class="muted">
      {{ tr('This bot does not support Bark notifications. Update its NFI image.') }}
    </p>
    <form v-else-if="settings && draft" class="space-y-5" @submit.prevent="submit()">
      <UBadge :color="settings.role === 'live' ? 'warning' : 'neutral'">{{
        settings.role === 'live' ? tr('Live trading') : tr('Paper trading')
      }}</UBadge>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Server notifications continue when your browser is closed. Paper and live bots save separate settings.',
          )
        }}
      </p>
      <USwitch v-model="draft.enabled" :disabled="busy" :label="tr('Enable Bark notifications')" />
      <UFormField
        :label="tr('Bark push URL')"
        :help="
          settings.destination_configured
            ? tr('A private destination is saved. Leave blank to keep it, or enter a replacement.')
            : tr(
                'Install Bark on your iPhone and copy its push URL, for example https://api.day.app/your-device-key. Self-hosted Bark servers are supported.',
              )
        "
      >
        <PasswordInput
          v-model="destination"
          autocomplete="off"
          :disabled="busy || clearDestination"
          :maxlength="2048"
          class="w-full"
        />
      </UFormField>
      <BaseCheckbox
        v-if="settings.destination_configured"
        v-model="clearDestination"
        :disabled="busy"
        >{{ tr('Remove the saved Bark destination (disable notifications first)') }}</BaseCheckbox
      >
      <fieldset :disabled="busy" class="space-y-4">
        <legend class="font-semibold mb-3">{{ tr('Notification events') }}</legend>
        <div class="grid sm:grid-cols-2 gap-4">
          <div class="space-y-2">
            <BaseCheckbox v-model="draft.profit_enabled">{{
              tr('Profit target reached')
            }}</BaseCheckbox>
            <UFormField :label="tr('Profit threshold (%)')">
              <UInputNumber
                v-model="draft.profit_threshold_pct"
                :min="0.01"
                :max="100000"
                :step="0.01"
                :disabled="!draft.profit_enabled"
                class="w-full"
              />
            </UFormField>
          </div>
          <div class="space-y-2">
            <BaseCheckbox v-model="draft.loss_enabled">{{
              tr('Loss threshold reached')
            }}</BaseCheckbox>
            <UFormField :label="tr('Loss threshold (%, positive value)')">
              <UInputNumber
                v-model="draft.loss_threshold_pct"
                :min="0.01"
                :max="100"
                :step="0.01"
                :disabled="!draft.loss_enabled"
                class="w-full"
              />
            </UFormField>
          </div>
        </div>
        <BaseCheckbox v-model="draft.state_enabled">{{ tr('Bot state changed') }}</BaseCheckbox>
        <UFormField :label="tr('Cooldown per event (minutes)')" class="max-w-md">
          <UInputNumber
            v-model="draft.cooldown_minutes"
            :min="5"
            :max="1440"
            :step="5"
            class="w-full"
          />
        </UFormField>
      </fieldset>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Return = cumulative trading profit / bot starting capital, including fees, partial exits and open-position profit. It is not monthly return or account balance change. A loss threshold of 3 means return at or below -3%.',
          )
        }}
      </p>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'Checked every 60 seconds, including while the bot is stopped. A threshold sends once until return leaves its trigger range and crosses again after the cooldown. Enabling or changing a threshold can alert on the current value. Failed threshold deliveries retry after 5 minutes.',
          )
        }}
      </p>
      <p class="muted text-sm leading-relaxed">
        {{
          tr(
            'State alerts cover running, stopped and paused states observed by the monitor. Container downtime and brief changes between checks cannot be reported. Notifications do not place or close orders.',
          )
        }}
      </p>
      <UFormField :label="tr('Bark administrator password')" class="max-w-md">
        <PasswordInput
          v-model="password"
          autocomplete="current-password"
          :disabled="busy"
          :maxlength="1024"
          class="w-full"
        />
      </UFormField>
      <div class="flex flex-wrap gap-3">
        <UButton
          type="submit"
          :loading="busy"
          :disabled="!changed || !valid || !password || busy || !!freeze.remaining"
          >{{ tr('Save Bark settings') }}</UButton
        >
        <UButton
          type="button"
          color="neutral"
          :disabled="
            changed || !settings.destination_configured || !password || busy || !!freeze.remaining
          "
          @click="submit(true)"
          >{{ tr('Send Bark test notification') }}</UButton
        >
      </div>
      <p class="muted text-sm">
        {{
          tr(
            'Save changes before testing. Tests use the saved destination and work even when automatic notifications are disabled.',
          )
        }}
      </p>
      <div class="border-t border-default pt-4 space-y-3">
        <h3 class="font-semibold">{{ tr('Bark monitoring status') }}</h3>
        <p v-if="!settings.enabled" class="muted">
          {{ tr('Automatic notifications are disabled.') }}
        </p>
        <UAlert
          v-else-if="settings.monitor_error"
          color="warning"
          :title="message(settings.monitor_error)"
        />
        <p v-else-if="!settings.last_checked_at" class="muted">
          {{ tr('Waiting for the first server check.') }}
        </p>
        <p v-if="settings.last_checked_at" class="text-sm break-words">
          {{ tr('Last check:') }} {{ new Date(settings.last_checked_at).toLocaleString() }}
          <span v-if="settings.roi_pct !== null">
            · {{ tr('Trading return:') }} {{ settings.roi_pct.toFixed(2) }}%</span
          >
        </p>
        <p class="muted text-sm">
          {{
            tr(
              'Reload to see the latest status and delivery history. A successful send means Bark accepted it; device delivery depends on Bark and iOS settings.',
            )
          }}
        </p>
        <ul v-if="settings.history.length" class="space-y-2 text-sm">
          <li
            v-for="(item, index) in settings.history"
            :key="index"
            class="flex flex-wrap gap-x-3 gap-y-1"
          >
            <span>{{ new Date(item.at).toLocaleString() }}</span>
            <span>{{ eventLabel(item.event) }}</span>
            <UBadge :color="item.success ? 'success' : 'error'">{{
              item.success ? tr('Accepted by Bark') : tr('Delivery failed')
            }}</UBadge>
          </li>
        </ul>
        <p v-else class="muted text-sm">{{ tr('No Bark deliveries recorded yet.') }}</p>
      </div>
    </form>
  </section>
</template>
