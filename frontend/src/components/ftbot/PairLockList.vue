<script setup lang="ts">
import { tr } from '@/i18n';
import type { Lock } from '@/types';
import type { TableColumn } from '@nuxt/ui';

const botStore = useBotStore();

const columns: TableColumn<Lock>[] = [
  { accessorKey: 'pair', header: tr('Pair') },
  { accessorKey: 'lock_end_timestamp', header: tr('Until') },
  { accessorKey: 'reason', header: tr('Reason') },
  { id: 'actions', header: tr('Actions') },
];

function removePairLock(item: Lock) {
  console.log(item);
  if (item.id !== undefined) {
    botStore.activeBot.deleteLock(item.id);
  } else {
    showAlert(tr('This Freqtrade version does not support deleting locks.'));
  }
}
</script>

<template>
  <div>
    <div class="mb-2">
      <label class="me-auto text-xl">{{ tr('Pair Locks') }}</label>
      <UButton
        class="float-end"
        color="neutral"
        icon="mdi:refresh"
        @click="botStore.activeBot.getLocks"
      />
    </div>
    <UTable
      :data="botStore.activeBot.activeLocks"
      :columns="columns"
      :ui="{
        td: 'whitespace-normal',
      }"
    >
      <template #lock_end_timestamp-cell="{ row }">
        {{ timestampms(row.original.lock_end_timestamp) }}
      </template>
      <template #actions-cell="{ row }">
        <UButton
          class="btn-xs ms-1"
          size="sm"
          color="neutral"
          :title="tr('Delete Lock')"
          icon="mdi:delete"
          @click="removePairLock(row.original)"
        />
      </template>
    </UTable>
  </div>
</template>
