// Local recipe deployment check. Explicit initialization only saves/applies the unchanged default recipe.
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

const base = process.env.NFI_RESEARCH_TEST_URL;
const container = process.env.NFI_RESEARCH_TEST_CONTAINER;
if (!base?.startsWith('http://127.0.0.1:') || !container)
  throw new Error('Specify the local research URL and Compose bot container explicitly');
const script = `
import json,os
from nfi_account.credentials import AccountManager
from freqtrade.rpc.api_server.api_auth import create_token
api={'username':os.environ['FREQTRADE__API_SERVER__USERNAME'],'jwt_secret_key':os.environ['FREQTRADE__API_SERVER__JWT_SECRET_KEY']}
AccountManager({'api_server':api,'user_data_dir':'/freqtrade/user_data'})
data={'identity':{'u':api['username']}}
print(json.dumps({'username':api['username'],'accessToken':create_token(data,api['jwt_secret_key']),'refreshToken':create_token(data,api['jwt_secret_key'],'refresh')}))
`;
// Credentials stay in a private pipe and this temporary browser context; never print them.
const credentials = JSON.parse(
  execFileSync('docker', ['exec', container, 'python', '-c', script], { encoding: 'utf8' }),
);
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
const page = await browser.newPage({
  viewport: { width: 1440, height: 1100 },
  reducedMotion: 'reduce',
});
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
await page.addInitScript(
  ({ base, credentials }) => {
    localStorage.setItem(
      'ftAuthLoginInfo',
      JSON.stringify({
        researchCheck: { ...credentials, botName: 'NFI 模拟盘', apiUrl: base, autoRefresh: true },
      }),
    );
  },
  { base, credentials },
);
try {
  const headers = { Authorization: 'Bearer ' + credentials.accessToken };
  async function recipe() {
    const response = await page.request.get(base + '/api/v1/recipe', { headers });
    if (!response.ok()) throw new Error('Recipe API unavailable: ' + response.status());
    return response.json();
  }
  let data = await recipe();
  if (process.env.NFI_RECIPE_INITIALIZE === '1') {
    expect(data.saved.revision).toBe(0);
    expect(data.saved.settings).toEqual(data.defaults);
    expect(data.applied_settings).toEqual(data.defaults);
    const saved = await page.request.put(base + '/api/v1/recipe', {
      headers,
      data: { revision: 0, settings: data.defaults },
    });
    expect(saved.status()).toBe(200);
    data = await saved.json();
    const applied = await page.request.post(base + '/api/v1/recipe/apply', {
      headers,
      data: { revision: data.saved.revision },
    });
    expect(applied.status()).toBe(200);
    await expect
      .poll(
        async () => {
          try {
            return (await recipe()).applied_revision;
          } catch {
            return -1;
          }
        },
        { timeout: 90000, intervals: [3000] },
      )
      .toBe(data.saved.revision);
  }
  data = await recipe();
  expect(data.applied_settings).toEqual(data.saved.settings);
  await page.goto(base + '/recipes');
  await expect(page.getByRole('heading', { name: '策略配方', exact: true })).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByLabel('最大持仓数', { exact: true })).toHaveValue(
    String(data.saved.settings.max_open_trades),
  );
  await expect(page.getByLabel('固定回测币池', { exact: true })).toHaveValue(
    data.saved.settings.research_pairs.join('\n'),
  );
  await mkdir('../artifacts/recipe-preview', { recursive: true });
  await page.screenshot({ path: '../artifacts/recipe-preview/recipe-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true);
  await page.screenshot({ path: '../artifacts/recipe-preview/recipe-mobile.png', fullPage: true });
  const response = await page.request.get(base + '/api/v1/research/info', { headers });
  expect(response.status()).toBe(200);
  const info = await response.json();
  expect(info.pairs).toEqual(data.saved.settings.research_pairs);
  expect(info.recipe_revision).toBe(data.saved.revision);
  expect(info.fee).toBe(data.saved.settings.fee);
  if (process.env.NFI_RECIPE_VERIFY_BACKTEST === '1') {
    const today = new Date();
    const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
    const start = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - 1, 1));
    const dates = {
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
    const download = await page.request.post(base + '/api/v1/research/prepare', {
      headers,
      data: dates,
    });
    expect(download.status()).toBe(200);
    let phase = '';
    await expect
      .poll(
        async () => {
          const response = await page.request.get(base + '/api/v1/research/info', { headers });
          if (!response.ok()) return 'unavailable';
          const current = (await response.json()).preparation;
          if (current.timeframe !== phase) {
            phase = current.timeframe;
            console.log('Preparing recipe candles: ' + phase);
          }
          if (current.status === 'failed') throw new Error('Recipe candle preparation failed');
          return current.status;
        },
        { timeout: 1200000, intervals: [5000] },
      )
      .toBe('success');
    const launched = await page.request.post(base + '/api/v1/research/backtest', {
      headers,
      data: {
        strategy: 'NostalgiaForInfinityX8',
        timeframe: '5m',
        timerange: dates.start_date.replaceAll('-', '') + '-' + dates.end_date.replaceAll('-', ''),
        dry_run_wallet: 10000,
        enable_protections: true,
        backtest_cache: 'none',
      },
    });
    expect(launched.status()).toBe(200);
    let result;
    await expect
      .poll(
        async () => {
          const response = await page.request.get(base + '/api/v1/research/backtest', { headers });
          if (!response.ok()) return 'unavailable';
          const current = await response.json();
          if (current.status === 'error') throw new Error('Recipe backtest failed');
          result = current.backtest_result?.strategy?.NostalgiaForInfinityX8;
          return current.status;
        },
        { timeout: 1200000, intervals: [5000] },
      )
      .toBe('ended');
    expect(result.pairlist.length).toBe(info.pairs.length);
    const report = {
      dates,
      recipe_revision: data.saved.revision,
      pairs: result.pairlist.length,
      trades: result.total_trades,
      profit_usdt: result.profit_total_abs,
      return_ratio: result.profit_total,
      drawdown_ratio: result.max_drawdown_account,
      starting_balance: result.starting_balance,
      final_balance: result.final_balance,
      fee_per_side: info.fee,
    };
    await writeFile(
      '../artifacts/recipe-preview/validation.json',
      JSON.stringify(report, null, 2) + '\n',
    );
    console.log('Recipe historical validation: ' + JSON.stringify(report));
  }
  if (errors.length) throw new Error('Browser errors occurred during the recipe deployment check');
  console.log(
    'Recipe deployment passed: revision ' +
      data.saved.revision +
      ', ' +
      info.pairs.length +
      ' research pairs, persistent defaults, paper reload, Chinese desktop and mobile.',
  );
} finally {
  await browser.close();
}
