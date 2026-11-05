import { Injectable } from '@angular/core';
import { safeFlightUrl } from '../core/format';
import type { Monitor } from '../core/types';
import { flightNumbers } from './shared/presentation';

export interface MonitorPresentation {
  description: string;
  match: string;
  airlines: string[];
  bookingUrl: string | undefined;
  bookingLabel: string;
}

interface MonitorPresentationStrategy {
  present(monitor: Monitor): MonitorPresentation;
}

class SelectedItineraryPresentation implements MonitorPresentationStrategy {
  present(monitor: Monitor): MonitorPresentation {
    return {
      description: flightNumbers(monitor.target.segments) || 'Selected itinerary',
      match: '',
      airlines: [
        ...new Set(
          monitor.target.segments
            .flatMap((segment) => segment.legs)
            .map((leg) => leg.airline)
            .filter((code): code is string => !!code),
        ),
      ],
      bookingUrl: safeFlightUrl(monitor.target.url),
      bookingLabel: 'View flight',
    };
  }
}

class RouteSearchPresentation implements MonitorPresentationStrategy {
  present(monitor: Monitor): MonitorPresentation {
    const offer = monitor.latest?.observed_offer;
    return {
      description: 'Cheapest matching route',
      match: offer ? flightNumbers(offer.segments) : '',
      airlines: [
        ...new Set(
          (offer?.segments ?? [])
            .flatMap((segment) => segment.legs)
            .map((leg) => leg.airline)
            .filter((code): code is string => !!code),
        ),
      ],
      bookingUrl: safeFlightUrl(offer?.url ?? monitor.target.url),
      bookingLabel: offer ? 'View flight' : 'View search',
    };
  }
}

/** Strategy selects the right observed offer without leaking provider rules into templates. */
@Injectable({ providedIn: 'root' })
export class MonitorPresenter {
  private readonly strategies: Record<'selected' | 'search', MonitorPresentationStrategy> = {
    selected: new SelectedItineraryPresentation(),
    search: new RouteSearchPresentation(),
  };

  present(monitor: Monitor): MonitorPresentation {
    return this.strategies[monitor.target.kind === 'search' ? 'search' : 'selected'].present(
      monitor,
    );
  }
}
