import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

/** The two alert rules, tried on an example price history. */
@Component({
  selector: 'ff-rule-demo',
  templateUrl: './rule-demo.component.html',
  styleUrl: './rule-demo.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RuleDemoComponent {
  readonly alertMode = signal<'new_low' | 'below_price'>('new_low');
}
