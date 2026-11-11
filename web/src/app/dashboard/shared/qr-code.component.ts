import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { encode } from 'uqr';

/**
 * A QR code drawn as one SVG path, so it stays sharp at any zoom and needs no
 * inline style. Authenticator apps and 1Password's "scan QR code" read it.
 */
@Component({
  selector: 'ff-qr-code',
  standalone: true,
  template: `<svg
    class="qr"
    [attr.viewBox]="'0 0 ' + size() + ' ' + size()"
    role="img"
    [attr.aria-label]="label()"
    shape-rendering="crispEdges"
  >
    <rect class="qr-ground" [attr.width]="size()" [attr.height]="size()" />
    <path class="qr-ink" [attr.d]="path()" />
  </svg>`,
  styles: `
    :host {
      display: block;
    }
    .qr {
      display: block;
      width: 100%;
      height: auto;
    }
    .qr-ground {
      fill: #fff;
    }
    .qr-ink {
      fill: var(--ff-ink);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class QrCodeComponent {
  readonly value = input.required<string>();
  readonly label = input('QR code');
  private readonly code = computed(() => encode(this.value(), { ecc: 'M', border: 2 }));
  readonly size = computed(() => this.code().data.length);
  readonly path = computed(() => {
    let d = '';
    this.code().data.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) d += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return d;
  });
}
