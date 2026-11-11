import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';

@Component({
  selector: 'ff-dialog',
  standalone: true,
  templateUrl: './dialog.component.html',
  styleUrl: './dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DialogComponent implements AfterViewInit, OnDestroy {
  readonly title = input.required<string>();
  readonly closed = output<void>();
  readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');
  private previous: HTMLElement | null = null;

  ngAfterViewInit(): void {
    this.previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.dialog().nativeElement.showModal();
  }

  /** Set while the sheet slides away; the parent removes it once that has finished. */
  readonly closing = signal(false);

  dismiss(event?: Event): void {
    event?.preventDefault();
    if (this.closing()) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return void this.closed.emit();
    this.closing.set(true);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      this.closed.emit();
    };
    this.dialog().nativeElement.addEventListener('animationend', finish, { once: true });
    // In case the animation never runs (a hidden tab, for example).
    setTimeout(finish, 320);
  }

  ngOnDestroy(): void {
    this.dialog().nativeElement.close();
    const previous = this.previous;
    requestAnimationFrame(() => previous?.isConnected && previous.focus());
  }
}
