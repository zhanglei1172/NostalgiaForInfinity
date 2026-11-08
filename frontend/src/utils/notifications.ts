import { tr } from '@/i18n';
import type { FTWsMessage } from '@/types/wsMessageTypes';
import { FtWsMessageTypes } from '@/types/wsMessageTypes';

export function showNotification(msg: FTWsMessage, botname: string) {
  const settingsStore = useSettingsStore();
  if (settingsStore.notifications && settingsStore.notifications[msg.type]) {
    switch (msg.type) {
      case FtWsMessageTypes.entryFill:
        console.log('entryFill', msg);
        showAlert(
          tr('Entry fill: {0} {1} at {2}', { 0: msg.pair, 1: msg.direction, 2: msg.open_rate }),
          'success',
          botname,
        );
        break;
      case FtWsMessageTypes.exitFill:
        console.log('exitFill', msg);
        showAlert(
          tr('Exit fill: {0} {1} {2}', { 0: msg.pair, 1: msg.direction, 2: msg.open_rate }),
          'success',
          botname,
        );
        break;
      case FtWsMessageTypes.exitCancel:
        console.log('exitCancel', msg);
        showAlert(
          tr('Exit order cancelled for {0} due to {1}', { 0: msg.pair, 1: msg.reason }),
          'warning',
          botname,
        );
        break;
      case FtWsMessageTypes.entryCancel:
        console.log('entryCancel', msg);
        showAlert(
          tr('Entry order cancelled for {0} due to {1}', { 0: msg.pair, 1: msg.reason }),
          'warning',
          botname,
        );
        break;
    }
  } else {
    console.log(`${botname}: Message ${msg.type} not shown.`);
  }
}
