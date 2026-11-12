import { ChangeDetectionStrategy, Component, OnInit, inject, output, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { safeFlightUrl } from '../../core/format';
import { RegionalFormat } from '../../core/regional-format';
import type { AdminFlight, AdminFlights } from '../../core/types';
import { ActionState } from '../shared/action-state';
import { flightNumbers } from '../shared/presentation';
import { flightStateLabels, flightStateTone, routeOf, tripShape } from './admin-labels';

/** Every flight the service checks, once per itinerary, with who watches it. */
@Component({
  selector: 'ff-admin-flights',
  standalone: true,
  templateUrl: './admin-flights.component.html',
  styleUrls: ['./admin-table.scss', './admin-flights.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminFlightsComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly format = inject(RegionalFormat);
  readonly choose = output<string>();
  readonly data = signal<AdminFlights | null>(null);
  readonly action = new ActionState();
  readonly stateLabels = flightStateLabels;
  readonly stateTone = flightStateTone;
  readonly routeOf = routeOf;
  readonly tripShape = tripShape;
  readonly flightNumbers = flightNumbers;
  readonly safeFlightUrl = safeFlightUrl;

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    await this.action.run(async () => {
      this.data.set(await this.api.request<AdminFlights>('/v1/admin/flights'));
    });
  }

  price(flight: AdminFlight): string {
    return flight.latest
      ? this.format.money(flight.latest.amount_minor, flight.latest.currency)
      : '–';
  }

  open(event: Event, account: string): void {
    event.preventDefault();
    this.choose.emit(account);
  }
}
