import { ChangeDetectionStrategy, Component, OnInit, inject, input } from '@angular/core';
import { TelegramFacade } from '../../core/telegram.facade';

/** Connects, checks and disconnects Telegram; the same control wherever it is offered. */
@Component({
  selector: 'ff-telegram-connect',
  standalone: true,
  templateUrl: './telegram-connect.component.html',
  styleUrl: './telegram-connect.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TelegramConnectComponent implements OnInit {
  readonly telegram = inject(TelegramFacade);
  /** Offer to disconnect once connected; off where the control is only an invitation. */
  readonly manage = input(true);

  ngOnInit(): void {
    void this.telegram.load();
  }
}
