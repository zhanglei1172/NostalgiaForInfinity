<script setup lang="ts">
import { tr } from '@/i18n';
import type { RecipeInfo, RecipeSettings } from '@/types/recipe';
import { recipeFields as fields } from '@/utils/recipeFields';

const bots = useBotStore();
const { confirm } = useConfirmBox();
const info = ref<RecipeInfo>();
const form = ref<RecipeSettings>();
const pairs = ref('');
const busy = ref(false);
const error = ref('');
const notice = ref('');
const pendingRevision = ref<number>();
let generation = 0;
const parsedPairs = computed(() =>
  pairs.value
    .toUpperCase()
    .split(/[\s,;]+/)
    .filter(Boolean),
);
const candidate = computed(() =>
  form.value ? { ...form.value, research_pairs: parsedPairs.value } : undefined,
);
const dirty = computed(
  () => info.value && JSON.stringify(candidate.value) !== JSON.stringify(info.value.saved.settings),
);
const valid = computed(() => {
  if (!form.value) return false;
  return (
    fields.every((field) => {
      const value = form.value![field.key] * field.scale;
      return (
        Number.isFinite(value) &&
        value >= field.min &&
        value <= field.max &&
        (field.scale !== 1 || Number.isInteger(value))
      );
    }) &&
    parsedPairs.value.length >= 3 &&
    parsedPairs.value.length <= 80 &&
    new Set(parsedPairs.value).size === parsedPairs.value.length &&
    parsedPairs.value.every((pair) => /^[A-Z0-9]{2,20}\/USDT$/.test(pair))
  );
});
function api() {
  const id = bots.selectedBot;
  return useApi(useLoginInfo(id), id).api;
}
function edit(settings: RecipeSettings) {
  form.value = { ...settings, research_pairs: [...settings.research_pairs] };
  pairs.value = settings.research_pairs.join('\n');
}
function failure(value: unknown) {
  if (isApiError(value) && value.status === 409)
    return tr('The recipe changed in another session. Reload it before saving or applying.');
  if (isApiError(value) && value.status === 422)
    return tr(
      'Check parameter ranges and pair symbols. Blacklisted or leveraged assets are not allowed.',
    );
  return tr('Unable to update the recipe. Retry or check the service logs.');
}
async function load() {
  const current = ++generation;
  if (bots.activeBot?.botState.nfi_live_management) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  info.value = undefined;
  form.value = undefined;
  pendingRevision.value = undefined;
  try {
    const data = await api()<RecipeInfo>('/recipe');
    if (current !== generation) return;
    info.value = data;
    edit(data.saved.settings);
  } catch (value) {
    if (current === generation) error.value = failure(value);
  } finally {
    if (current === generation) busy.value = false;
  }
}
async function save() {
  if (!info.value || !candidate.value || !valid.value || busy.value) return;
  const current = generation;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const data = await api()<RecipeInfo>('/recipe', {
      method: 'PUT',
      body: { revision: info.value.saved.revision, settings: candidate.value },
    });
    if (current !== generation) return;
    info.value = data;
    edit(data.saved.settings);
    notice.value = tr('Saved. The next research download and backtest will use this recipe.');
  } catch (value) {
    if (current === generation) error.value = failure(value);
  } finally {
    if (current === generation) busy.value = false;
  }
}
async function apply() {
  if (!info.value?.can_apply || dirty.value || busy.value || pendingRevision.value !== undefined)
    return;
  const current = generation;
  const revision = info.value.saved.revision;
  if (
    !(await confirm({
      title: tr('Apply recipe to paper bot'),
      message: tr(
        'Reload the paper bot with the saved recipe? Existing trades, the database and the initial wallet are preserved. Open positions will use the new configuration. The bot will stop after reload; review it before starting again.',
      ),
    }))
  )
    return;
  if (current !== generation) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    await api()('/recipe/apply', { method: 'POST', body: { revision } });
    if (current === generation) pendingRevision.value = revision;
  } catch (value) {
    if (current === generation) error.value = failure(value);
  } finally {
    if (current === generation) busy.value = false;
  }
}
useIntervalFn(async () => {
  if (pendingRevision.value === undefined) return;
  const current = generation;
  try {
    const data = await api()<RecipeInfo>('/recipe');
    if (current !== generation) return;
    info.value = data;
    if (data.applied_revision === pendingRevision.value) {
      pendingRevision.value = undefined;
      notice.value = tr('The saved recipe is now active on the paper bot.');
    }
  } catch {
    /* The API is briefly unavailable during reload. Keep the pending status visible. */
  }
}, 3000);
watch(() => bots.selectedBot, load);
onMounted(load);
</script>

<template>
  <LiveRecipeSettings v-if="bots.activeBot?.botState.nfi_live_management" />
  <div v-else class="workspace-page recipe-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ info?.exchange?.toUpperCase() ?? 'NFI' }} · SPOT · NFI X8</p>
        <h1>{{ tr('Recipe settings') }}</h1>
        <p>{{ tr('A reproducible paper trading baseline with bounded, useful controls.') }}</p>
      </div>
      <UButton to="/backtest" color="neutral" icon="i-mdi-flask-outline">{{
        tr('Backtesting')
      }}</UButton>
    </div>
    <UAlert v-if="error" :title="error" color="error" role="alert" class="mb-6" />
    <UAlert v-if="notice" :title="notice" color="success" role="status" class="mb-6" />
    <UAlert
      v-if="pendingRevision !== undefined"
      :title="tr('Reload requested. Waiting for the paper bot to report the applied revision…')"
      color="info"
      role="status"
      class="mb-6"
    />
    <div v-if="!info || !form" class="workspace-panel p-6">
      <p v-if="busy">{{ tr('Loading…') }}</p>
      <UButton v-else @click="load">{{ tr('Retry') }}</UButton>
    </div>
    <template v-else>
      <section class="workspace-panel p-6 mb-6 recipe-context">
        <h2>
          {{
            tr('{exchange} spot paper baseline v1', {
              exchange: info.exchange?.toUpperCase() ?? 'NFI',
            })
          }}
        </h2>
        <p>
          {{
            tr('Saved revision: {saved} · Paper bot revision: {applied}', {
              saved: info.saved.revision,
              applied: info.applied_revision ?? '—',
            })
          }}
        </p>
        <p>
          {{
            tr(
              'Fixed: USDT, unlimited stake allocation, 5m candles, exit signals enabled and loss exits allowed. Strategy stop and de-risk logic stay enabled.',
            )
          }}
        </p>
        <p>
          {{
            tr(
              'Paper trading selects a dynamic volume pool. Research uses the fixed pairs below; historical liquidity and listing filters are not reproduced. A current pair selection can introduce survivorship bias.',
            )
          }}
        </p>
        <p>
          {{
            tr(
              'Start with the defaults, change one parameter at a time, then compare the same dates, pairs and fees on a separate validation period. This baseline has no proven profit target.',
            )
          }}
        </p>
      </section>
      <form class="workspace-panel p-6" @submit.prevent="save">
        <div class="recipe-grid">
          <UFormField
            v-for="field in fields"
            :key="field.key"
            :label="tr(field.label)"
            :help="tr(field.help)"
          >
            <UInputNumber
              :model-value="Number((form[field.key] * field.scale).toFixed(10))"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :increment="false"
              :decrement="false"
              :disabled="busy || pendingRevision !== undefined"
              class="w-full"
              @update:model-value="
                form[field.key] = Number((($event ?? 0) / field.scale).toFixed(10))
              "
            />
          </UFormField>
          <UFormField
            :label="tr('Fixed research pairs')"
            :help="
              tr(
                '3–80 unique BASE/USDT symbols, one per line. Default: 40 established assets. Changing pairs requires downloading their history again. This list does not limit the dynamic paper pool.',
              )
            "
            class="col-span-full"
          >
            <UTextarea
              v-model="pairs"
              :rows="8"
              class="w-full font-mono"
              :disabled="busy || pendingRevision !== undefined"
            />
          </UFormField>
        </div>
        <p v-if="!valid" class="text-error mt-4">
          {{
            tr(
              'Check parameter ranges and pair symbols. Blacklisted or leveraged assets are not allowed.',
            )
          }}
        </p>
        <div class="recipe-actions">
          <UButton
            type="submit"
            :disabled="busy || !dirty || !valid || pendingRevision !== undefined"
            :loading="busy"
            >{{ tr('Save for research') }}</UButton
          >
          <UButton
            type="button"
            color="neutral"
            :disabled="
              busy ||
              dirty ||
              !info.can_apply ||
              pendingRevision !== undefined ||
              info.applied_revision === info.saved.revision
            "
            @click="apply"
            >{{ tr('Apply recipe to paper bot') }}</UButton
          >
          <UButton
            type="button"
            color="neutral"
            variant="outline"
            :disabled="busy || pendingRevision !== undefined"
            @click="edit(info.defaults)"
            >{{ tr('Restore default values') }}</UButton
          >
          <UButton
            type="button"
            color="neutral"
            variant="ghost"
            :disabled="busy || pendingRevision !== undefined"
            @click="load"
            >{{ tr('Reload saved recipe') }}</UButton
          >
        </div>
        <p class="muted mt-4 text-sm">
          {{
            tr(
              'Save first, then apply to paper trading separately. Applying never resets the 10,000 USDT wallet or closes existing trades. Recipe values take priority over matching environment variables. Live trading is not supported here.',
            )
          }}
        </p>
        <details v-if="info.applied_settings" class="mt-5">
          <summary>{{ tr('Currently applied paper parameters') }}</summary>
          <dl class="recipe-grid mt-3">
            <div v-for="field in fields" :key="field.key">
              <dt class="muted">{{ tr(field.label) }}</dt>
              <dd>
                {{
                  Number(
                    (info.applied_settings[field.key] * field.scale).toFixed(10),
                  ).toLocaleString()
                }}
              </dd>
            </div>
          </dl>
        </details>
      </form>
    </template>
  </div>
</template>
<style scoped>
.recipe-page {
  max-width: 1200px;
}
.recipe-context {
  display: grid;
  gap: 12px;
}
.recipe-context p {
  color: var(--ui-text-muted);
  line-height: 1.7;
  font-size: 0.875rem;
}
.recipe-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 28px;
}
.recipe-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}
@media (max-width: 640px) {
  .recipe-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
