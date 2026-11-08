<script setup lang="ts">
import { tr } from '@/i18n';
import { FtWsMessageTypes } from '@/types/wsMessageTypes';

const settingsStore = useSettingsStore();
const colorStore = useColorStore();

const timezoneOptions = ['UTC', Intl.DateTimeFormat().resolvedOptions().timeZone];
const openTradesOptions = [
  { value: OpenTradeVizOptions.showPill, text: tr('Show pill in icon') },
  { value: OpenTradeVizOptions.asTitle, text: tr('Show in title') },
  { value: OpenTradeVizOptions.noOpenTrades, text: tr("Don't show open trades in header") },
];
const colorPreferenceOptions = [
  { value: ColorPreferences.GREEN_UP, text: tr('Green Up/Red Down') },
  { value: ColorPreferences.RED_UP, text: tr('Red Up/Green Down') },
];
</script>

<template>
  <div class="workspace-page settings-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">{{ tr('PREFERENCES') }}</p>
        <h1>{{ tr('Settings') }}</h1>
        <p>{{ tr('Manage bot startup, server notifications and browser preferences.') }}</p>
      </div>
    </div>
    <div
      class="workspace-panel max-w-4xl p-6 mb-6 flex items-center justify-between gap-4 flex-wrap"
    >
      <div>
        <h2 class="section-title">{{ tr('Account & security') }}</h2>
        <p class="muted text-sm mt-2">
          {{ tr('Change your password and manage logins for this bot.') }}
        </p>
      </div>
      <UButton to="/account" icon="i-mdi-account-lock-outline">{{ tr('Manage account') }}</UButton>
    </div>
    <BotStartupSettings />
    <BotBarkSettings />
    <UCard class="max-w-4xl">
      <template #header
        ><span class="text-2xl font-bold">{{ tr('FreqUI Settings') }}</span></template
      >
      <div class="flex flex-col gap-4 text-start dark:text-neutral-300">
        <div class="flex flex-wrap items-center gap-3">
          <span>{{ tr('Interface language') }}</span>
          <LanguageSelect />
          <small
            >{{ tr('Language preference is saved in this browser.') }}
            {{ tr('Changing language resets unsaved forms.') }}</small
          >
        </div>
        <p class="text-left">{{ tr('UI Version:') }} {{ settingsStore.uiVersion }}</p>

        <div class="border border-neutral-400 rounded-sm p-4 space-y-4">
          <h4 class="text-xl font-semibold">{{ tr('UI settings') }}</h4>

          <USeparator />

          <div class="space-y-1">
            <label class="block text-sm">{{ tr('Show open trades in header') }}</label>
            <USelect
              v-model="settingsStore.openTradesInTitle"
              :items="openTradesOptions"
              label-key="text"
              value-key="value"
              class="w-full"
            />
            <small class="text-sm text-neutral-600 dark:text-neutral-400">{{
              tr('Decide if open trades should be visualized')
            }}</small>
          </div>

          <div class="space-y-1">
            <label class="block text-sm">{{ tr('UTC Timezone') }}</label>
            <USelect v-model="settingsStore.timezone" :items="timezoneOptions" class="w-full" />
            <small class="text-sm text-neutral-600 dark:text-neutral-400">{{
              tr('Select timezone (UTC is recommended as exchanges usually work in UTC)')
            }}</small>
          </div>

          <BaseCheckbox v-model="settingsStore.backgroundSync" class="space-y-1">
            {{ tr('Background sync') }}
            <template #hint>
              {{ tr('Keep background sync running while other bots are selected.') }}
            </template>
          </BaseCheckbox>

          <BaseCheckbox v-model="settingsStore.confirmDialog" class="space-y-1">
            {{ tr('Show Confirm Dialog for Trade Exits') }}
            <template #hint
              >{{ tr('Use confirmation dialogs when force-exiting a trade.') }}<br />
              {{ tr('This will also show') }} <i-mdi-run-fast class="text-yellow-300 inline" />
              <i-mdi-alert class="text-yellow-300 inline" />
              {{ tr('in the title bar.') }}
            </template>
          </BaseCheckbox>
        </div>

        <div class="border border-neutral-400 rounded-sm p-4 space-y-4">
          <h4 class="text-lg font-semibold">{{ tr('Chart settings') }}</h4>

          <div class="space-y-1">
            <label class="block text-sm">{{ tr('Chart scale Side') }}</label>
            <URadioGroup
              v-model="settingsStore.chartLabelSide"
              :items="[
                { label: tr('Left'), value: 'left' },
                { label: tr('Right'), value: 'right' },
              ]"
              orientation="horizontal"
            />
            <small class="text-sm text-neutral-600 dark:text-neutral-400">
              {{ tr('Should the scale be displayed on the right or left?') }}
            </small>
          </div>

          <BaseCheckbox v-model="settingsStore.useHeikinAshiCandles" class="space-y-1">
            {{ tr('Use Heikin Ashi candles') }}
            <template #hint>{{ tr('Use Heikin Ashi candles in your charts') }}</template>
          </BaseCheckbox>

          <BaseCheckbox v-model="settingsStore.useReducedPairCalls" class="space-y-1">
            {{ tr('Only request necessary columns') }}
            <template #hint>{{
              tr(
                'Can reduce the transfer size for large dataframes. May require additional calls if the plot config changes.',
              )
            }}</template>
          </BaseCheckbox>

          <div>
            <p>{{ tr('Default number of candles to display (defaults to 250)') }}</p>
            <div class="flex flex-row gap-5 w-full items-center">
              <USlider
                v-model="settingsStore.chartDefaultCandleCount"
                class="flex-1"
                :step="50"
                :min="100"
                :max="2000"
              />
              <UInputNumber
                v-model="settingsStore.chartDefaultCandleCount"
                :step="50"
                :min="100"
                :max="2000"
                size="sm"
              />
            </div>
          </div>

          <div class="space-y-1">
            <label class="block">{{ tr('Candle Color Preference') }}</label>
            <div class="flex flex-row gap-5 items-center">
              <URadioGroup
                v-model="colorStore.colorPreference"
                :items="colorPreferenceOptions"
                label-key="text"
                value-key="value"
                orientation="horizontal"
              >
                <template #label="{ item }">
                  <div class="flex items-center">
                    <span class="mr-2">{{ item.text }}</span>
                    <UIcon
                      name="mdi:arrow-up-thin"
                      :color="
                        item.value === ColorPreferences.GREEN_UP
                          ? colorStore.colorProfit
                          : colorStore.colorLoss
                      "
                      class="-ml-2 size-5"
                    />
                    <UIcon
                      name="mdi:arrow-down-thin"
                      :color="
                        item.value === ColorPreferences.GREEN_UP
                          ? colorStore.colorLoss
                          : colorStore.colorProfit
                      "
                      class="-ml-2 size-5"
                    />
                  </div>
                </template>
              </URadioGroup>
            </div>
          </div>
        </div>

        <div class="border rounded-sm border-neutral-400 p-4 space-y-4">
          <h4 class="text-lg font-semibold">{{ tr('Browser notifications') }}</h4>
          <div class="space-y-2">
            <BaseCheckbox v-model="settingsStore.notifications[FtWsMessageTypes.entryFill]">
              {{ tr('Entry notifications') }}
            </BaseCheckbox>
            <BaseCheckbox v-model="settingsStore.notifications[FtWsMessageTypes.exitFill]">
              {{ tr('Exit notifications') }}
            </BaseCheckbox>
            <BaseCheckbox v-model="settingsStore.notifications[FtWsMessageTypes.entryCancel]">
              {{ tr('Entry Cancel notifications') }}
            </BaseCheckbox>
            <BaseCheckbox v-model="settingsStore.notifications[FtWsMessageTypes.exitCancel]">
              {{ tr('Exit Cancel notifications') }}
            </BaseCheckbox>
          </div>
        </div>

        <div class="border rounded-sm border-neutral-400 p-4 space-y-4">
          <h4 class="text-lg font-semibold">{{ tr('Backtesting settings') }}</h4>
          <div>
            <label for="backtestMetrics" class="block">{{ tr('Backtesting metrics') }}</label>
            <USelectMenu
              multiple
              id="backtestMetrics"
              v-model="settingsStore.backtestAdditionalMetrics"
              :items="availableBacktestMetrics"
              label-key="header"
              value-key="field"
              class="w-full"
              display="chip"
            />
            <small class="text-sm text-neutral-600 dark:text-neutral-400">{{
              tr('Select which metrics should be shown on a per pair / tag basis.')
            }}</small>
          </div>
        </div>
      </div>
    </UCard>
  </div>
</template>
