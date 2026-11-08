<script setup lang="ts">
import { tr } from '@/i18n';
import type { BotDescriptor } from '@/types';
const { confirm } = useConfirmBox();

const props = defineProps<{
  bot: BotDescriptor;
  noButtons?: boolean;
  noRefreshSwitch?: boolean;
  noText?: boolean;
}>();

defineEmits<{ edit: [botId: string]; editLogin: [botId: string] }>();

const botStore = useBotStore();

function confirmRemoveBot() {
  botStore.removeBot(props.bot.botId);
}

async function removeBotQuestion() {
  if (
    await confirm({
      title: tr('Logout confirmation'),
      message: tr('Really remove (logout) from {0} ({1})?', {
        0: props.bot.botName,
        1: props.bot.botId,
      }),
    })
  ) {
    confirmRemoveBot();
  }
}

const selectedBotStore = computed<BotSubStore>(() => {
  return botStore.botStores[props.bot.botId]!;
});

const autoRefreshLoc = computed({
  get() {
    return selectedBotStore.value.autoRefresh;
  },
  set(newValue) {
    selectedBotStore.value.setAutoRefresh(newValue);
  },
});
</script>

<template>
  <div v-if="bot" class="flex items-center justify-between w-full">
    <span v-if="!noText" class="me-2">{{ bot.botName || bot.botId }}</span>

    <div class="flex items-center gap-2">
      <div class="flex items-center">
        <USwitch
          v-if="!noRefreshSwitch"
          v-model="autoRefreshLoc"
          class="mr-2"
          :title="tr('Auto refresh for {0}', { 0: bot.botName || bot.botId })"
        />
        <div
          v-if="selectedBotStore.isBotLoggedIn"
          :title="selectedBotStore.isBotOnline ? tr('Online') : tr('Offline')"
        >
          <i-mdi-circle
            class="mx-1"
            :class="selectedBotStore.isBotOnline ? 'text-green-500' : 'text-red-500'"
          />
        </div>
        <div v-else :title="tr('Login info expired, please login again.')">
          <i-mdi-cancel class="text-red-500 mx-1" />
        </div>
      </div>

      <div class="flex items-center gap-1">
        <UButton
          v-if="!noButtons && selectedBotStore.isBotLoggedIn"
          color="neutral"
          variant="soft"
          :title="tr('Edit bot')"
          @click="$emit('edit', bot.botId)"
          icon="mdi:pencil"
        />
        <UButton
          v-if="!noRefreshSwitch && !selectedBotStore.isBotLoggedIn"
          variant="soft"
          color="neutral"
          :title="tr('Login again')"
          @click="$emit('editLogin', bot.botId)"
          icon="mdi:login"
        />
        <UButton
          v-if="!noButtons"
          variant="soft"
          color="neutral"
          :title="tr('Delete bot')"
          @click="removeBotQuestion"
          icon="mdi:delete"
        />
      </div>
    </div>
  </div>
</template>
