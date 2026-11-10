import { ChangeDetectionStrategy, Component, input, output, signal } from '@angular/core';

@Component({
  selector: 'ff-secret',
  standalone: true,
  templateUrl: './secret.component.html',
  styleUrl: './secret.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SecretComponent {
  readonly fieldId = 'secret-' + crypto.randomUUID();
  readonly title = input.required<string>();
  readonly value = input.required<string>();
  /** Inside another titled surface: no heading or panel of its own. */
  readonly plain = input(false);
  readonly confirmLabel = input('I’ve saved it');
  readonly dismissed = output<void>();
  readonly copied = signal(false);
  readonly error = signal('');

  async copy(): Promise<void> {
    this.error.set('');
    try {
      await navigator.clipboard.writeText(this.value());
      this.copied.set(true);
    } catch {
      this.error.set('Copy is unavailable. Select the code and copy it manually.');
    }
  }

  download(): void {
    const url = URL.createObjectURL(
      new Blob([this.title() + '\n' + this.value() + '\n'], { type: 'text/plain' }),
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download =
      'fareflare-' +
      this.title()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-') +
      '.txt';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
