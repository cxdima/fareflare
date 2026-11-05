import { signal } from '@angular/core';
import { message } from '../../core/format';

/** A component-owned command boundary: prevents duplicate actions and exposes feedback. */
export class ActionState {
  readonly busy = signal(false);
  readonly error = signal('');

  async run<T>(command: () => Promise<T>): Promise<T | undefined> {
    if (this.busy()) return undefined;
    this.busy.set(true);
    this.error.set('');
    try {
      return await command();
    } catch (cause) {
      this.error.set(message(cause));
      return undefined;
    } finally {
      this.busy.set(false);
    }
  }
}
