import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  effect,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import { scrolledThrough } from '../core/motion';

const SMALL_SCREEN = 720;
const LOADS_AT_ONCE = 6;

/**
 * A run of still frames drawn to a canvas and scrubbed by scrolling, the way a
 * product turns in your hand as you move down a page. A single still stands in
 * until `live` is set, and stays for anyone who asked for less motion.
 */
@Component({
  selector: 'ff-scroll-sequence',
  templateUrl: './scroll-sequence.component.html',
  styleUrl: './scroll-sequence.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.is-live]': 'live()' },
})
export class ScrollSequenceComponent {
  /** Folder holding `poster.webp`, `w1440/000.webp…` and `w800/000.webp…`. */
  readonly base = input.required<string>();
  readonly frames = input.required<number>();
  readonly framesSmall = input.required<number>();
  /** The tall element whose scroll distance plays the run from first frame to last. */
  readonly track = input.required<HTMLElement>();
  readonly live = input(false);
  /** Eased position in the run, from 0 to 1, each time it moves. */
  readonly progress = output<number>();

  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private images: (HTMLImageElement | undefined)[] = [];
  private folder = '';
  private target = 0;
  private current = 0;
  private drawn = -1;
  private frame = 0;
  private started = false;

  constructor() {
    effect(() => {
      if (this.live() && !this.started) this.start();
    });
    inject(DestroyRef).onDestroy(() => {
      removeEventListener('scroll', this.measure);
      removeEventListener('resize', this.measure);
      cancelAnimationFrame(this.frame);
    });
  }

  private start(): void {
    this.started = true;
    const small = innerWidth < SMALL_SCREEN;
    this.folder = `${this.base()}/${small ? 'w800' : 'w1440'}`;
    this.images = new Array(small ? this.framesSmall() : this.frames());
    this.target = this.current = scrolledThrough(this.track());
    // The frame under the reader comes first; the rest wait until the run is close.
    this.load(this.wanted()).then(() => this.paint());
    const near = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        near.disconnect();
        void this.loadAll();
      },
      { rootMargin: '150% 0px' },
    );
    near.observe(this.host);
    addEventListener('scroll', this.measure, { passive: true });
    addEventListener('resize', this.measure, { passive: true });
  }

  private wanted(): number {
    return Math.round(this.current * (this.images.length - 1));
  }

  /** One frame. A frame that fails is asked for once more before it is left out. */
  private load(index: number, retry = true): Promise<void> {
    if (this.images[index]) return Promise.resolve();
    return new Promise((resolve) => {
      const image = new Image();
      image.decoding = 'async';
      image.onload = () => {
        this.images[index] = image;
        resolve();
      };
      image.onerror = () => {
        if (!retry) return resolve();
        setTimeout(() => void this.load(index, false).then(resolve), 1500);
      };
      image.src = `${this.folder}/${String(index).padStart(3, '0')}.webp`;
    });
  }

  /** Nearest frames first, so a reader who lands mid-run is not left waiting on frame 0. */
  private async loadAll(): Promise<void> {
    const from = this.wanted();
    const order = Array.from(this.images.keys()).sort(
      (a, b) => Math.abs(a - from) - Math.abs(b - from),
    );
    let next = 0;
    const worker = async (): Promise<void> => {
      while (next < order.length) {
        await this.load(order[next++]);
        this.paint();
      }
    };
    await Promise.all(Array.from({ length: LOADS_AT_ONCE }, worker));
  }

  private readonly measure = (): void => {
    this.target = scrolledThrough(this.track());
    if (!this.frame) this.frame = requestAnimationFrame(this.step);
  };

  /** Follows the scroll position with a little give, so a wheel notch does not jump frames. */
  private readonly step = (): void => {
    this.frame = 0;
    const gap = this.target - this.current;
    this.current = Math.abs(gap) < 0.0008 ? this.target : this.current + gap * 0.22;
    this.paint();
    this.progress.emit(this.current);
    if (this.current !== this.target) this.frame = requestAnimationFrame(this.step);
  };

  private paint(): void {
    const index = this.nearestLoaded(this.wanted());
    if (index < 0 || index === this.drawn) return;
    const image = this.images[index]!;
    const canvas = this.canvas().nativeElement;
    if (canvas.width !== image.naturalWidth) {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
    }
    canvas.getContext('2d')?.drawImage(image, 0, 0);
    this.drawn = index;
  }

  /** While frames are still arriving, hold the closest one that has. */
  private nearestLoaded(index: number): number {
    for (let reach = 0; reach < this.images.length; reach++) {
      if (this.images[index - reach]) return index - reach;
      if (this.images[index + reach]) return index + reach;
    }
    return -1;
  }
}
