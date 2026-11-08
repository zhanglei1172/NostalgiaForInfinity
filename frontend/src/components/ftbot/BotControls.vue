<script setup lang="ts">
import { tr } from '@/i18n';
import type { ForceExitPayload } from '@/types';

const botStore = useBotStore();
const { confirm } = useConfirmBox();

const { forceEntryDialog } = useForceTrade();

const isRunning = computed((): boolean => {
  return botStore.activeBot.botState?.state === 'running';
});

async function handleStopBot() {
  const result = await confirm({
    title: tr('Stop Bot'),
    message: tr('Stop the bot loop from running?'),
  });
  if (result) {
    botStore.activeBot.stopBot();
  }
}

async function handleStopBuy() {
  if (
    await confirm({
      title: tr('Pause - Stop Entering'),
      message: tr(
        'Freqtrade will continue to handle open trades, but will not enter new trades or increase position sizes. Really stop entering?',
      ),
    })
  ) {
    botStore.activeBot.stopBuy();
  }
}

async function handleReloadConfig() {
  if (
    await confirm({
      title: tr('Reload Config'),
      message: tr('Reload configuration (including strategy)?'),
    })
  ) {
    botStore.activeBot.reloadConfig();
  }
}

async function handleForceExit() {
  if (
    await confirm({
      title: tr('ForceExit all'),
      message: tr('Really forceexit ALL trades?'),
    })
  ) {
    const payload: ForceExitPayload = {
      tradeid: 'all',
      // TODO: support ordertype (?)
    };
    botStore.activeBot.forceexit(payload);
  }
}

async function handleForceEntry() {
  await forceEntryDialog({
    pair: botStore.activeBot.selectedPair,
  });
}
</script>

<template>
  <div class="flex flex-row flex-wrap gap-2">
    <UButton
      size="md"
      color="neutral"
      :disabled="!botStore.activeBot.isTrading || isRunning"
      :title="tr('Start Trading')"
      icon="mdi:play"
      :label="tr('Start')"
      @click="botStore.activeBot.startBot()"
    />
    <UButton
      size="md"
      color="error"
      :disabled="!botStore.activeBot.isTrading || !isRunning"
      :title="tr('Stop Trading - Also stops handling open trades.')"
      icon="mdi:stop"
      :label="tr('Stop')"
      @click="handleStopBot()"
    />
    <UButton
      size="md"
      color="neutral"
      :disabled="!botStore.activeBot.isTrading || !isRunning"
      :title="
        tr(
          'Pause (StopBuy) - Freqtrade will continue to handle open trades, but will not enter new trades or increase position sizes.',
        )
      "
      icon="mdi:pause"
      :label="tr('Pause entries')"
      @click="handleStopBuy()"
    />
    <UButton
      size="md"
      color="neutral"
      :disabled="!botStore.activeBot.isTrading"
      :title="
        tr(
          'Reload Config - reloads configuration including strategy, resetting all settings changed on the fly.',
        )
      "
      icon="mdi:reload"
      :label="tr('Reload Config')"
      @click="handleReloadConfig()"
    />
    <UButton
      color="error"
      size="md"
      :disabled="!botStore.activeBot.isTrading"
      :title="tr('Force exit all')"
      icon="mdi:close-box-multiple"
      :label="tr('Exit all positions')"
      @click="handleForceExit()"
    />
    <UButton
      v-if="botStore.activeBot.botState && botStore.activeBot.botState.force_entry_enable"
      size="md"
      color="neutral"
      :disabled="!botStore.activeBot.isTrading || !isRunning"
      :title="
        tr(
          'Force enter - Immediately enter a trade at an optional price. Exits are then handled according to strategy rules.',
        )
      "
      icon="mdi:plus-box-multiple-outline"
      :label="tr('Manual entry')"
      @click="handleForceEntry"
    />
  </div>
</template>
