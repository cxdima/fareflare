import { ChangeDetectionStrategy, Component, afterNextRender, signal } from '@angular/core';
import { allowsMotion } from '../core/motion';
import { ScrollSequenceComponent } from './scroll-sequence.component';

/**
 * How it works, told by one object: a paper plane that unfolds into a baggage
 * tag as the three steps go by, then takes an example fare as its print.
 */
@Component({
  selector: 'ff-how',
  imports: [ScrollSequenceComponent],
  templateUrl: './how.component.html',
  styleUrl: './how.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HowComponent {
  /** Off until the browser confirms motion is welcome: the still version is the default. */
  readonly motion = signal(false);
  readonly step = signal(0);
  readonly printed = signal(true);

  constructor() {
    afterNextRender(() => {
      if (!allowsMotion()) return;
      this.printed.set(false);
      this.motion.set(true);
    });
  }

  /** The plane is the link, the unfolded tag is the rule, the print is the recorded price. */
  follow(progress: number): void {
    this.step.set(progress < 0.3 ? 0 : progress < 0.68 ? 1 : 2);
    this.printed.set(progress > 0.87);
  }
}
