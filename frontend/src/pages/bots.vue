<script setup lang="ts">
import { tr } from '@/i18n';

definePage({ meta: { allowAnonymous: true } });
const bots = useBotStore();
const router = useRouter();
const loginDialog = useLoginDialog();
const mode = ref<'spot' | 'futures'>('futures');
const name = ref('okx-futures');
const port = ref(18082);
const origin = ref(window.location.origin);
const copied = ref(false);
const valid = computed(() => {
  try {
    const url = new URL(origin.value);
    return (
      /^[a-z][a-z0-9-]{0,30}$/.test(name.value) &&
      Number.isInteger(port.value) &&
      port.value >= 1024 &&
      port.value <= 65535 &&
      ['http:', 'https:'].includes(url.protocol) &&
      url.origin === origin.value
    );
  } catch {
    return false;
  }
});
const quote = (text: string) => "'" + text.replaceAll("'", "'\\''") + "'";
const command = computed(() =>
  valid.value
    ? [
        `python tools/bots.py create --name ${quote(name.value)} --mode ${mode.value} --port ${port.value} --console-origin ${quote(origin.value)}`,
        `docker compose -f user_data/bots/${name.value}/compose.json build bot`,
        `docker compose -f user_data/bots/${name.value}/compose.json up -d bot`,
      ].join('\n')
    : '',
);
const connections = computed(() =>
  bots.availableBotsSorted.map((bot) => ({
    ...bot,
    runtime: bots.botStores[bot.botId],
  })),
);
watch(mode, (value) => {
  if (name.value === 'okx-spot' || name.value === 'okx-futures') name.value = `okx-${value}`;
});
async function copy() {
  if (!valid.value) return;
  try {
    await navigator.clipboard.writeText(command.value);
    copied.value = true;
  } catch {
    copied.value = false;
  }
}
function select(id: string) {
  bots.selectBot(id);
  void router.push('/dashboard');
}
</script>

<template>
  <div class="workspace-page bots-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">NOSTALGIA FOR INFINITY</p>
        <h1>{{ tr('Bot management') }}</h1>
        <p>
          {{
            tr('Run independent spot and futures instances and switch between them in one console.')
          }}
        </p>
      </div>
      <UButton icon="i-mdi-lan-connect" @click="loginDialog({})">{{
        tr('Connect existing bot')
      }}</UButton>
    </div>
    <section class="workspace-panel p-6 mb-6">
      <h2 class="section-title mb-4">{{ tr('Connected bots') }}</h2>
      <p v-if="!connections.length" class="muted">
        {{ tr('No bots connected. Deploy an instance below, then connect its Web address.') }}
      </p>
      <div class="bot-grid">
        <article v-for="bot in connections" :key="bot.botId" class="bot-card">
          <div class="flex items-center justify-between gap-3">
            <h3>{{ bot.botName || bot.botId }}</h3>
            <UBadge :color="bot.runtime?.isBotOnline ? 'success' : 'neutral'">{{
              tr(bot.runtime?.isBotOnline ? 'Online' : 'Offline')
            }}</UBadge>
          </div>
          <p class="muted text-sm mt-2 break-all">{{ bot.botUrl }}</p>
          <div v-if="bot.runtime?.botStatusAvailable" class="flex flex-wrap gap-2 mt-3">
            <UBadge color="neutral">{{
              tr(bot.runtime.botState.trading_mode === 'futures' ? 'Isolated futures' : 'Spot')
            }}</UBadge>
            <UBadge :color="bot.runtime.botState.dry_run ? 'neutral' : 'warning'">{{
              tr(bot.runtime.botState.dry_run ? 'Paper trading' : 'Live trading')
            }}</UBadge>
            <span class="text-sm">{{ tr('Open trades') }}: {{ bot.runtime.openTradeCount }}</span>
          </div>
          <div class="flex flex-wrap gap-3 mt-4">
            <UButton :disabled="!bot.runtime?.isBotLoggedIn" @click="select(bot.botId)">{{
              tr('Open workspace')
            }}</UButton>
            <UButton :href="bot.botUrl" target="_blank" color="neutral" variant="outline">{{
              tr('Open own console')
            }}</UButton>
          </div>
        </article>
      </div>
    </section>
    <section class="workspace-panel p-6">
      <h2 class="section-title">{{ tr('Deploy a new instance') }}</h2>
      <p class="muted mt-2">
        {{
          tr(
            'Run these commands in the repository on your Docker host. Each instance has its own account, database, budget, startup preference and notifications.',
          )
        }}
      </p>
      <div class="deploy-grid mt-5">
        <UFormField :label="tr('Instance name')"
          ><UInput v-model="name" class="w-full" :maxlength="31"
        /></UFormField>
        <UFormField :label="tr('Trading mode')"
          ><USelect
            v-model="mode"
            class="w-full"
            :items="[
              { label: tr('Spot'), value: 'spot' },
              { label: tr('Isolated futures'), value: 'futures' },
            ]"
        /></UFormField>
        <UFormField :label="tr('Local Web port')"
          ><UInputNumber v-model="port" class="w-full" :min="1024" :max="65535"
        /></UFormField>
        <UFormField
          :label="tr('Shared console origin')"
          :help="
            tr(
              'Only this exact Web origin may manage the new bot from another console. Add further trusted origins in its Compose settings.',
            )
          "
          ><UInput v-model="origin" class="w-full"
        /></UFormField>
      </div>
      <p v-if="!valid" class="text-error mt-4">
        {{
          tr('Enter a lowercase instance name, an unused port and a valid HTTP(S) console origin.')
        }}
      </p>
      <pre v-else class="deployment-command mt-5" data-testid="deployment-command">{{
        command
      }}</pre>
      <UButton
        class="mt-4"
        :disabled="!valid"
        color="neutral"
        icon="i-mdi-content-copy"
        @click="copy"
        >{{ tr(copied ? 'Copied' : 'Copy deployment commands') }}</UButton
      >
      <ol class="list-decimal ps-5 mt-5 space-y-2">
        <li>
          {{
            tr(
              'Open the new local address or an SSH tunnel and create its administrator. No shared default password is used.',
            )
          }}
        </li>
        <li>
          {{
            tr(
              'Configure its OKX subaccount, API credentials and budget under Trading account. New bots remain stopped until you explicitly start them.',
            )
          }}
        </li>
        <li>
          {{
            tr(
              'Return here and connect the new bot using its reachable Web address and administrator login.',
            )
          }}
        </li>
      </ol>
      <p class="muted text-sm mt-5">
        {{
          tr(
            'Optional research runs in a separate container for this instance. Start it with the research Compose profile; spot and futures data and results remain separate.',
          )
        }}
      </p>
      <pre v-if="valid" class="deployment-command mt-3">
docker compose -f user_data/bots/{{ name }}/compose.json --profile research up -d</pre>
      <p class="text-sm mt-5">
        {{
          tr(
            'Use a separate instance and OKX subaccount for each bot. Two API keys for the same account do not isolate funds.',
          )
        }}
      </p>
    </section>
  </div>
</template>

<style scoped>
.bots-page {
  max-width: 1200px;
}
.bot-grid,
.deploy-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.bot-card {
  padding: 20px;
  border: 1px solid var(--ui-border);
  border-radius: 12px;
}
.deployment-command {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 16px;
  border-radius: 8px;
  background: var(--ui-bg-elevated);
  font-size: 13px;
}
@media (max-width: 640px) {
  .bot-grid,
  .deploy-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
