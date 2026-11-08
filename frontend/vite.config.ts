import { defineConfig } from 'vitest/config';

import createVuePlugin from '@vitejs/plugin-vue';
import ui from '@nuxt/ui/vite';
import { resolve } from 'path';
import IconsResolve from 'unplugin-icons/resolver';
import Icons from 'unplugin-icons/vite';
import VueRouter from 'vue-router/vite';

const commitHash = '4e1717a+nfi-ui.13';

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __COMMIT_HASH__: JSON.stringify(commitHash),
  },
  plugins: [
    // Must be registered before the Vue plugin so it can transform route blocks.
    VueRouter({
      routesFolder: 'src/pages',
      dts: 'src/typed-router.d.ts',
    }),
    createVuePlugin({
      script: {
        defineModel: true,
      },
    }),
    ui({
      icon: { clientBundle: { scan: true, sizeLimitKb: 256 } },
      ui: {
        colors: {
          primary: 'indigo',
          // slate, gray or mist
          neutral: 'slate',
        },
        alert: {
          defaultVariants: {
            variant: 'subtle',
          },
        },
        button: {
          slots: { base: 'rounded-lg' },
          defaultVariants: {
            variant: 'subtle',
          },
        },
        input: { slots: { base: 'rounded-lg' } },
        select: { slots: { base: 'rounded-lg' } },
        table: {
          slots: {
            td: 'px-2 py-2 text-default text-md text-left',
            th: 'px-2 py-2 text-default text-md',
          },
        },
        tabs: {
          variants: {
            variant: {
              link: {
                trigger: 'grow focus:outline-none',
              },
            },
          },
        },
      },
      autoImport: {
        imports: ['vue', 'vue-router', '@vueuse/core', 'pinia'],
        dts: 'src/auto-imports.d.ts',
        dirs: ['src/composables', 'src/stores', 'src/utils/**'],
        vueTemplate: true,
      },
      components: {
        resolvers: [IconsResolve()],
        dts: 'src/components.d.ts',
      },
    }),
    Icons({
      compiler: 'vue3',
    }),
  ],
  resolve: {
    dedupe: ['vue'],
    alias: {
      '@': resolve(import.meta.dirname, 'src'),
    },
  },
  optimizeDeps: {
    // Avoid optimized dependencies changed. reloading reload cycles
    include: [
      '@internationalized/date',
      '@tanstack/vue-table',
      '@vueuse/integrations/useSortable',
      'date-fns',
      'date-fns-tz',
      'deepmerge',
      'echarts',
      'echarts/charts',
      'echarts/components',
      'echarts/core',
      'echarts/features',
      'echarts/renderers',
      'favico.js',
      'humanize-duration',
      'ofetch',
      'reka-ui',
      'vue-echarts',
      'vue-router/experimental',
    ],
  },
  build: {
    chunkSizeWarningLimit: 700, // Default is 500
    sourcemap: true,
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.NFI_API_PROXY_TARGET ?? 'http://127.0.0.1:8080',
        changeOrigin: true,
        ws: true,
      },
    },
    host: '127.0.0.1',
    port: 3000,
  },
  test: {
    environment: 'happy-dom',
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/e2e/**',
      '**/.{idea,git,cache,output,temp}/**',
      '**/{karma,rollup,webpack,vite,vitest,jest,ava,babel,nyc,cypress,tsup,build}.config.*',
    ],
  },
});
