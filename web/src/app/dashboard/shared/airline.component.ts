import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

const airlines: Record<string, { name: string; asset?: string }> = {
  UA: { name: 'United Airlines', asset: 'UA.png' },
  AA: { name: 'American Airlines', asset: 'AA.png' },
  DL: { name: 'Delta Air Lines', asset: 'DL.png' },
  WN: { name: 'Southwest Airlines', asset: 'WN.png' },
  AS: { name: 'Alaska Airlines', asset: 'AS.png' },
  B6: { name: 'JetBlue', asset: 'B6.png' },
  F9: { name: 'Frontier Airlines', asset: 'F9.png' },
  NK: { name: 'Spirit Airlines', asset: 'NK.png' },
};

/** Only known, local assets are loaded; unrecognized carriers remain readable. */
@Component({
  selector: 'ff-airline',
  standalone: true,
  templateUrl: './airline.component.html',
  styleUrl: './airline.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AirlineComponent {
  readonly code = input.required<string>();
  readonly failedSource = signal('');
  readonly airline = computed(() => airlines[this.code().toUpperCase()]);
  readonly name = computed(() => this.airline()?.name ?? this.code());
  readonly source = computed(() => {
    const asset = this.airline()?.asset;
    return asset ? `/assets/airlines/${asset}` : '';
  });
}
