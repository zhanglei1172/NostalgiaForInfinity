<script setup lang="ts">
import { tr } from '@/i18n';
import { useAuthFreeze } from '@/composables/authFreeze';
import type { LiveRecipeInfo, RecipeSettings } from '@/types/recipe';
import { recipeFields } from '@/utils/recipeFields';

const bots = useBotStore();
const freeze = useAuthFreeze(() => bots.activeBot?.getLoginInfo().apiUrl ?? window.location.origin);
const { confirm } = useConfirmBox();
const info = ref<LiveRecipeInfo>();
const form = ref<RecipeSettings>();
const baseline = ref('');
const revision = ref(0);
const password = ref('');
const busy = ref(false);
const error = ref('');
const notice = ref('');
const pending = ref<number>();
let generation = 0;
const liveKeys = [
  'max_open_trades',
  'pair_limit',
  'min_age_days',
  'min_quote_volume',
  'max_spread_ratio',
  'max_slippage',
];
const fields = recipeFields.filter((field) => liveKeys.includes(field.key));
const dirty = computed(() => JSON.stringify(form.value) !== baseline.value);
const stale = computed(() => info.value && revision.value !== info.value.saved.revision);
const valid = computed(
  () =>
    form.value &&
    fields.every((field) => {
      const value = form.value![field.key] * field.scale;
      return (
        Number.isFinite(value) &&
        value >= field.min &&
        value <= field.max &&
        (field.scale !== 1 || Number.isInteger(value))
      );
    }),
);
const blocked = computed(() => busy.value || pending.value !== undefined);
const hasChanges = computed(
  () =>
    info.value &&
    form.value &&
    fields.some((field) => info.value!.applied_settings?.[field.key] !== form.value![field.key]),
);
const apiFor = (id: string) => useApi(useLoginInfo(id), id).api;
const messages: Record<string, string> = {
  live_origin_rejected:
    "The request origin was rejected. Open this bot's own Web address or check the reverse-proxy forwarding settings.",
  live_recipe_account_required:
    'Configure the OKX account before applying. A saved live draft will be used during first account setup.',
  live_apply_pending: 'Wait for the live service to finish loading before applying a recipe.',
  live_stop_required: 'Stop the live bot before applying a recipe.',
  live_recipe_has_positions:
    'Resolve open positions and orders before applying or rolling back a live recipe.',
  live_recipe_revision_conflict: 'The live configuration or draft changed. Reload before applying.',
  live_recipe_no_previous: 'There is no previous live recipe to restore.',
  account_guard_unavailable:
    'Password protection storage is unavailable. Verification is blocked; check storage permissions.',
  account_incorrect_password: 'The current password is incorrect.',
  account_rate_limited: 'Too many incorrect attempts. Try again in 5 minutes.',
  account_invalid_request: 'Check the recipe fields and confirm the live operation.',
};
function message(code: string | null | undefined) {
  return tr(
    messages[code ?? ''] ?? 'Unable to update the live recipe. Refresh the status and try again.',
  );
}
function failure(value: unknown) {
  if (freeze.capture(value)) return '';
  if (isApiError(value)) {
    if (value.status === 422)
      return tr(
        'Check parameter ranges and pair symbols. Blacklisted or leveraged assets are not allowed.',
      );
    return message(value.data?.detail);
  }
  return message(null);
}
function edit(settings: RecipeSettings) {
  form.value = { ...settings, research_pairs: [...settings.research_pairs] };
}
function accept(data: LiveRecipeInfo, reset: boolean) {
  info.value = data;
  if (reset) {
    edit(data.saved.settings);
    baseline.value = JSON.stringify(form.value);
    revision.value = data.saved.revision;
  }
  if (pending.value !== undefined) {
    if (data.phase === 'error') {
      pending.value = undefined;
      error.value = tr(
        'The live service failed to load the recipe. Check logs or restore the previous recipe after the service recovers.',
      );
    } else if (
      data.phase === 'ready' &&
      data.runtime_live_revision === pending.value &&
      data.live_revision === pending.value
    ) {
      pending.value = undefined;
      notice.value = tr(
        'The live recipe is active. The bot remains stopped; review it before starting.',
      );
    }
  }
}
async function load(reset = true) {
  const sequence = generation;
  const id = bots.selectedBot;
  if (reset) {
    password.value = '';
    error.value = '';
    notice.value = '';
    busy.value = true;
  }
  try {
    const data = await apiFor(id)<LiveRecipeInfo>('/live-recipe');
    if (sequence === generation) accept(data, reset);
  } catch (value) {
    if (sequence === generation && (reset || pending.value === undefined))
      error.value = failure(value);
  } finally {
    if (sequence === generation && reset) busy.value = false;
  }
}
async function save() {
  if (!info.value || !form.value || !valid.value || !dirty.value || blocked.value || stale.value)
    return;
  const sequence = generation;
  const id = bots.selectedBot;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = await apiFor(id)<LiveRecipeInfo>('/live-recipe', {
      method: 'PUT',
      body: { revision: revision.value, settings: form.value },
    });
    if (sequence !== generation) return;
    accept(data, true);
    notice.value = tr(
      'Live draft saved. The current live configuration and paper recipe are unchanged.',
    );
  } catch (value) {
    if (sequence === generation) error.value = failure(value);
  } finally {
    if (sequence === generation) busy.value = false;
  }
}
async function apply(rollback = false) {
  if (
    !info.value ||
    !password.value ||
    blocked.value ||
    freeze.remaining ||
    dirty.value ||
    stale.value ||
    !(rollback ? info.value.can_rollback : info.value.can_apply && hasChanges.value)
  )
    return;
  const sequence = generation;
  const id = bots.selectedBot;
  const expected = { revision: revision.value, live_revision: info.value.live_revision };
  if (
    !(await confirm({
      title: rollback ? tr('Restore previous live recipe') : tr('Apply recipe to live bot'),
      message: tr(
        'This changes the configuration used for real trading. The bot must be stopped with no open positions or orders. Account credentials, budget and history are preserved. Reload with this recipe and keep the bot stopped?',
      ),
    }))
  )
    return;
  if (sequence !== generation) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = await apiFor(id)<{ live_revision: number }>(
      '/live-recipe/' + (rollback ? 'rollback' : 'apply'),
      {
        method: 'POST',
        body: { ...expected, current_password: password.value, confirm_live: true },
      },
    );
    if (sequence !== generation) return;
    pending.value = data.live_revision;
    await load(rollback);
  } catch (value) {
    if (sequence === generation) error.value = failure(value);
  } finally {
    if (sequence === generation) {
      busy.value = false;
      password.value = '';
    }
  }
}
function display(settings: RecipeSettings | null | undefined, field: (typeof fields)[number]) {
  return settings ? Number((settings[field.key] * field.scale).toFixed(10)).toLocaleString() : '—';
}
watch(
  () => bots.selectedBot,
  () => {
    ++generation;
    info.value = undefined;
    form.value = undefined;
    pending.value = undefined;
    void load();
  },
  { immediate: true },
);
useIntervalFn(() => {
  if (!busy.value) void load(false);
}, 3000);
onBeforeUnmount(() => {
  ++generation;
  password.value = '';
});
</script>

<template>
  <div class="workspace-page live-recipe-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">OKX · SPOT · NFI X8</p>
        <h1>{{ tr('Recipe settings') }}</h1>
        <p>
          {{ tr('Independent live draft, configuration comparison and controlled application.') }}
        </p>
      </div>
      <UButton to="/backtest" color="neutral" icon="i-mdi-flask-outline">{{
        tr('Backtesting')
      }}</UButton>
    </div>
    <UAlert v-if="error" :title="error" role="alert" color="error" class="mb-6" />
    <UAlert v-if="notice" :title="notice" role="status" color="success" class="mb-6" />
    <UAlert
      v-if="pending !== undefined"
      :title="tr('Waiting for the live service to load the recipe. Trading will remain stopped.')"
      color="info"
      role="status"
      class="mb-6"
    />
    <div v-if="!info || !form" class="workspace-panel p-6">
      <p v-if="busy">{{ tr('Loading…') }}</p>
      <UButton v-else @click="load()">{{ tr('Retry') }}</UButton>
    </div>
    <template v-else>
      <section class="workspace-panel p-6 mb-6 space-y-3">
        <h2 class="section-title">{{ tr('Live configuration and paper comparison') }}</h2>
        <p class="muted text-sm">
          {{
            tr(
              'Live draft: {draft} · Applied live draft: {active} · Paper active: {paper} · Research saved: {research}',
              {
                draft: info.saved.revision,
                active:
                  info.runtime_revision ?? (info.runtime_settings ? tr('Initial snapshot') : '—'),
                paper: info.paper_applied.revision,
                research: info.paper_saved.revision,
              },
            )
          }}
        </p>
        <p class="muted text-sm">
          {{
            tr(
              'Real trading uses the OKX fee tier and the budget from Trading account. Simulation fee and balance-ratio fields do not apply to live trading.',
            )
          }}
        </p>
        <p class="muted text-sm">
          {{
            tr(
              'Applying or rolling back changes recipe parameters only. The live strategy code remains its saved X8 copy.',
            )
          }}
        </p>
        <p v-if="info.strategy.live_sha256" class="muted text-sm break-all">
          {{
            tr('Live strategy fingerprint: {hash}', {
              hash: info.strategy.live_sha256.slice(0, 12),
            })
          }}
        </p>
        <UAlert
          v-if="info.strategy.matches === false"
          color="warning"
          :title="
            tr(
              'The live X8 code differs from the research copy. Research results do not verify this exact live strategy.',
            )
          "
        />
        <UAlert v-if="info.apply_blocker" color="info" :title="message(info.apply_blocker)" />
        <UAlert
          v-if="stale"
          color="warning"
          :title="tr('The live configuration or draft changed. Reload before applying.')"
        />
        <div class="overflow-x-auto">
          <table class="w-full text-sm text-left live-recipe-table">
            <thead>
              <tr>
                <th>{{ tr('Parameter') }}</th>
                <th>{{ tr('Current live') }}</th>
                <th>{{ tr('Live draft') }}</th>
                <th>{{ tr('Paper active') }}</th>
                <th v-if="info.previous">{{ tr('Previous live') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="field in fields" :key="field.key">
                <th>{{ tr(field.label) }}</th>
                <td>{{ display(info.runtime_settings, field) }}</td>
                <td
                  :class="{
                    'text-warning font-semibold':
                      form[field.key] !== info.runtime_settings?.[field.key],
                  }"
                >
                  {{ display(form, field) }}
                </td>
                <td>{{ display(info.paper_applied.settings, field) }}</td>
                <td v-if="info.previous">{{ display(info.previous.settings, field) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <form class="workspace-panel p-6 space-y-6" @submit.prevent="save">
        <h2 class="section-title">{{ tr('Edit live draft') }}</h2>
        <div class="live-recipe-grid">
          <UFormField v-for="field in fields" :key="field.key" :label="tr(field.label)">
            <UInputNumber
              :model-value="Number((form[field.key] * field.scale).toFixed(10))"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :increment="false"
              :decrement="false"
              :disabled="blocked"
              class="w-full"
              @update:model-value="
                form[field.key] = Number((($event ?? 0) / field.scale).toFixed(10))
              "
            />
          </UFormField>
        </div>
        <div class="flex flex-wrap gap-3">
          <UButton type="submit" :disabled="blocked || !dirty || !valid || stale" :loading="busy">{{
            tr('Save live draft')
          }}</UButton>
          <UButton
            type="button"
            color="neutral"
            :disabled="blocked"
            @click="edit(info.paper_applied.settings)"
            >{{ tr('Copy applied paper recipe to draft') }}</UButton
          >
          <UButton type="button" color="neutral" :disabled="blocked" @click="load()">{{
            tr('Reload saved recipe')
          }}</UButton>
        </div>
        <p class="muted text-sm">
          {{
            tr(
              'Draft edits stay separate from paper trading and research. Save first, review the comparison, then apply explicitly.',
            )
          }}
        </p>
        <UFormField :label="tr('Current administrator password')" class="max-w-md"
          ><PasswordInput
            v-model="password"
            autocomplete="current-password"
            :disabled="blocked"
            class="w-full"
        /></UFormField>
        <div class="flex flex-wrap gap-3">
          <UButton
            type="button"
            color="warning"
            :disabled="
              blocked ||
              dirty ||
              stale ||
              !password ||
              !info.can_apply ||
              !hasChanges ||
              !!freeze.remaining
            "
            @click="apply()"
            >{{ tr('Apply recipe to live bot') }}</UButton
          >
          <UButton
            type="button"
            color="neutral"
            :disabled="
              blocked || dirty || stale || !password || !info.can_rollback || !!freeze.remaining
            "
            @click="apply(true)"
            >{{ tr('Restore previous live recipe') }}</UButton
          >
          <UButton to="/trading_settings" color="neutral" variant="ghost">{{
            tr('Trading account')
          }}</UButton>
        </div>
      </form>
    </template>
  </div>
</template>

<style scoped>
.live-recipe-page {
  max-width: 1200px;
}
.live-recipe-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.live-recipe-table th,
.live-recipe-table td {
  padding: 12px;
  border-bottom: 1px solid var(--workspace-border);
  white-space: nowrap;
}
@media (max-width: 639px) {
  .live-recipe-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
