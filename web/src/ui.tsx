import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { message } from './api';

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    plane: (
      <>
        <path d="m3 12 7-2 4-7 3 1-2 7 6 4-1 2-7-2-4 6-2-1 2-7-5 1z" />
      </>
    ),
    bell: (
      <>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
        <path d="M10 21h4" />
      </>
    ),
    link: (
      <>
        <path d="m10 13 4-4m-6 7-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0 12a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-1 1" />
      </>
    ),
    code: (
      <>
        <path d="m8 5-7 7 7 7m8-14 7 7-7 7m-3-17-2 20" />
      </>
    ),
    user: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
      </>
    ),
    plus: <path d="M12 4v16M4 12h16" />,
    arrow: <path d="M3 12h18m-6-6 6 6-6 6" />,
    refresh: (
      <>
        <path d="M20 7a9 9 0 0 0-15-2L2 8m0-6v6h6m-4 9a9 9 0 0 0 15 2l3-3m0 6v-6h-6" />
      </>
    ),
    check: <path d="m4 12 5 5L20 6" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    external: (
      <>
        <path d="M14 3h7v7M21 3 11 13M10 3H3v18h18v-7" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    shield: (
      <>
        <path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z" />
        <path d="m7 12 3 3 6-6" />
      </>
    ),
    key: (
      <>
        <circle cx="8" cy="8" r="5" />
        <path d="m12 12 9 9m-4-4 3-3m-6 0 3-3" />
      </>
    ),
    pause: (
      <>
        <path d="M8 4v16M16 4v16" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths[name] ?? paths.plane}
    </svg>
  );
}

export function Button({
  children,
  kind = 'secondary',
  busy = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  kind?: 'primary' | 'secondary' | 'danger' | 'ghost';
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      {...props}
      className={`button ${kind} ${props.className ?? ''}`}
      disabled={busy || props.disabled}
      aria-busy={busy || undefined}
    >
      {busy && <span className="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Notice({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return (
    <div className={`notice ${danger ? 'error' : ''}`} role={danger ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

export function Empty({
  title,
  children,
  icon = 'plane',
}: {
  title: string;
  children: ReactNode;
  icon?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={28} />
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}

export function Dialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const current = ref.current;
    current?.showModal();
    return () => {
      current?.close();
      requestAnimationFrame(() => previous?.focus());
    };
  }, []);
  return (
    <dialog ref={ref} aria-labelledby="dialog-title" onCancel={onClose} onClose={onClose}>
      <div className="dialog-heading">
        <h2 id="dialog-title">{title}</h2>
        <Button kind="ghost" onClick={onClose} aria-label="Close dialog">
          <Icon name="close" />
        </Button>
      </div>
      <div className="dialog-content">{children}</div>
    </dialog>
  );
}

export function Secret({
  title,
  value,
  onDismiss,
  children,
}: {
  title: string;
  value: string;
  onDismiss: () => void;
  children?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  return (
    <section className="secret-panel" aria-label={title}>
      <div className="eyebrow">Shown once</div>
      <h2>{title}</h2>
      <p>
        {children ??
          'Save this somewhere private. It will not be shown again after you leave this screen.'}
      </p>
      <textarea readOnly aria-label={title} value={value} rows={2} spellCheck={false} />
      <div className="actions">
        <Button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setCopied(true);
            } catch {
              setError('Select the text above and copy it manually.');
            }
          }}
        >
          {copied ? 'Copied' : 'Copy to clipboard'}
        </Button>
        <Button kind="ghost" onClick={onDismiss}>
          I’ve saved it
        </Button>
      </div>
      <span className="sr-only" role="status">
        {copied ? 'Copied to clipboard.' : ''}
      </span>
      {error && <p role="status">{error}</p>}
    </section>
  );
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    if (busy) return undefined;
    setBusy(true);
    setError('');
    try {
      return await action();
    } catch (cause) {
      setError(message(cause));
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, setError, run };
}

export const reasonLabel = (reason: string) =>
  ({
    tracking_started: 'Tracking started',
    new_low: 'New observed low',
    below_price: 'Below your target',
    rebound: 'Price increased',
  })[reason] ?? reason.replaceAll('_', ' ');

export function Status({ value }: { value: string }) {
  const label =
    {
      pending: 'Awaiting check',
      active: 'Watching',
      degraded: 'Check delayed',
      paused: 'Paused',
      cancelled: 'Stopped',
      expired: 'Departed',
      sent: 'Delivered',
      suppressed: 'Suppressed',
      dead_letter: 'Delivery failed',
      disabled: 'Disabled',
      deleted: 'Deleted',
      stale: 'Needs a fresh check',
    }[value] ?? value;
  return (
    <span className={`status status-${value}`}>
      <span className="status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
