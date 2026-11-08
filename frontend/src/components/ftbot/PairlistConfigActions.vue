<script setup lang="ts">
import { tr } from '@/i18n';
import EditValue from '../general/EditValue.vue';
const pairlistStore = usePairlistConfigStore();
</script>
<template>
  <div class="flex flex-col sm:flex-row mb-2 gap-2">
    <UButton
      :title="tr('Save configuration')"
      variant="solid"
      icon="mdi:content-save"
      @click="pairlistStore.saveConfig(pairlistStore.config.name)"
    />
    <EditValue
      v-model="pairlistStore.config.name"
      editable-name="config"
      :allow-add="true"
      :allow-duplicate="true"
      :allow-edit="true"
      class="flex grow"
      @delete="pairlistStore.deleteConfig"
      @duplicate="(oldName: string, newName: string) => pairlistStore.duplicateConfig(newName)"
      @new="(name: string) => pairlistStore.newConfig(name)"
      @rename="(oldName: string, newName: string) => pairlistStore.saveConfig(newName)"
    >
      <USelect
        v-model="pairlistStore.configName"
        class="w-full text-start"
        :items="pairlistStore.savedConfigs.map((c) => c.name)"
        @update:model-value="(config) => pairlistStore.selectOrCreateConfig(config as string)"
      />
    </EditValue>
    <UButton
      :title="tr('Evaluate pairlist')"
      :disabled="pairlistStore.evaluating || !pairlistStore.pairlistValid"
      variant="solid"
      @click="pairlistStore.startPairlistEvaluation()"
      :loading="pairlistStore.evaluating"
      :label="tr('Evaluate')"
      icon="mdi:play-box-outline"
    />
  </div>
</template>
