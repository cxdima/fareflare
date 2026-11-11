import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { flightLinkNote, keepPendingLink } from '../core/flight-link';

/** The first screen: the promise, the one field that starts everything, and an example alert. */
@Component({
  selector: 'ff-hero',
  templateUrl: './hero.component.html',
  styleUrl: './hero.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeroComponent {
  /** The link field: the product's one move, offered before an account exists. */
  readonly link = signal('');
  readonly linkNote = computed(() => flightLinkNote(this.link()));
  readonly github = 'https://github.com/cxdima/fareflare';

  /** A recognized link travels to sign-up and is waiting in the add-flight dialog afterwards. */
  start(event: Event, field: HTMLInputElement): void {
    event.preventDefault();
    const note = this.linkNote();
    if (note && !note.ok) {
      field.focus();
      return;
    }
    if (note) keepPendingLink(this.link());
    location.assign('/register');
  }
}
