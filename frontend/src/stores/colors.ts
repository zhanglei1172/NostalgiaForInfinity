const STORE_UI_COLORS = 'ftUIColorSettings';

export enum ColorPreferences {
  GREEN_UP = 'greenUp',
  RED_UP = 'redUp',
}

const COLOR_GREEN = '#26A69A';
const COLOR_RED = '#EF5350';

export const useColorStore = defineStore(
  'colorStore',
  () => {
    const colorPreference = ref(ColorPreferences.GREEN_UP);
    const colorUp = ref(COLOR_GREEN);
    const colorDown = ref(COLOR_RED);
    const settings = useSettingsStore();
    const colorProfit = computed(() => (settings.isDarkTheme ? '#34d399' : '#087f5b'));
    const colorLoss = computed(() => (settings.isDarkTheme ? '#ff7b86' : '#c92a3b'));

    const cssVars = computed(() => {
      return {
        '--color-profit': colorProfit.value,
        '--color-loss': colorLoss.value,
      };
    });

    function updateProfitLossColor() {
      const [nextColorUp, nextColorDown] =
        colorPreference.value === ColorPreferences.GREEN_UP
          ? [COLOR_GREEN, COLOR_RED]
          : [COLOR_RED, COLOR_GREEN];
      colorUp.value = nextColorUp;
      colorDown.value = nextColorDown;
    }

    return {
      colorPreference,
      colorUp,
      colorDown,
      colorProfit,
      colorLoss,
      cssVars,
      updateProfitLossColor,
    };
  },
  {
    persist: {
      key: STORE_UI_COLORS,
      pick: ['colorPreference'],
    },
  },
);

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useColorStore, import.meta.hot));
}
