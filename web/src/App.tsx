import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, message, setCsrfToken } from './api';
import type { Account, AccountResponse, Monitor, Page, ProductConfig, Webhook } from './types';
import { Auth } from './Auth';
import { Monitors } from './Monitors';
import { Alerts } from './Alerts';
import { Developer, Webhooks } from './Integrations';
import { Settings } from './Settings';
import { Button, Icon, Notice, Secret, useAction } from './ui';

const navigation = [
  { id: 'monitors', label: 'Flight monitors', icon: 'plane' },
  { id: 'alerts', label: 'Alert activity', icon: 'bell' },
  { id: 'webhooks', label: 'Webhooks', icon: 'link' },
  { id: 'developer', label: 'API & MCP', icon: 'code' },
  { id: 'settings', label: 'Account settings', icon: 'user' },
];
function currentView() {
  const hash = location.hash.slice(1).split('?')[0];
  return navigation.some((item) => item.id === hash) ? hash : 'monitors';
}

type ConsentDetails = {
  client_name?: string;
  name?: string;
  client_id: string;
  scopes: string[];
  resource: string;
  redirect_uri?: string;
};
function Consent({ id }: { id: string }) {
  const [details, setDetails] = useState<ConsentDetails | null>(null);
  const action = useAction();
  useEffect(() => {
    void action.run(async () =>
      setDetails(await api<ConsentDetails>(`/v1/oauth/requests/${encodeURIComponent(id)}`)),
    );
  }, [id]);
  async function decide(approve: boolean) {
    await action.run(async () => {
      const result = await api<{ redirect_url: string }>(
        `/v1/oauth/requests/${encodeURIComponent(id)}`,
        { method: 'POST', body: { approve } },
      );
      const target = new URL(result.redirect_url);
      if (!['http:', 'https:'].includes(target.protocol))
        throw new Error('The server returned an unsupported redirect URL.');
      location.assign(target.href);
    });
  }
  return (
    <div className="consent-page">
      <section className="panel">
        <span className="feature-icon">
          <Icon name="shield" size={26} />
        </span>
        <h1>Connect an application</h1>
        {action.error && <Notice danger>{action.error}</Notice>}
        {details ? (
          <>
            <p>
              <strong>{details.client_name ?? details.name ?? 'This application'}</strong> wants
              access to your account.
            </p>
            <dl className="consent-details">
              <dt>Callback address</dt>
              <dd>{details.redirect_uri ?? 'Not provided'}</dd>
              <dt>Client identifier</dt>
              <dd>{details.client_id}</dd>
              <dt>Resource</dt>
              <dd>{details.resource}</dd>
              <dt>Requested scopes</dt>
              <dd>{details.scopes.join(', ') || 'Account access'}</dd>
            </dl>
            <div className="info-panel">
              <strong>What this allows</strong>
              <p>
                Read your monitors and price history, create or change monitors, and manage
                monitoring settings through MCP. Approve only an application you recognize and
                trust.
              </p>
            </div>
            <div className="actions end">
              <Button busy={action.busy} onClick={() => void decide(false)}>
                Deny access
              </Button>
              <Button kind="primary" busy={action.busy} onClick={() => void decide(true)}>
                Allow access
              </Button>
            </div>
          </>
        ) : (
          <p>Loading access request…</p>
        )}
      </section>
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<ProductConfig | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState('');
  const [view, setView] = useState(currentView);
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [dataError, setDataError] = useState('');
  const [recovery, setRecovery] = useState('');
  const loading = useRef(false);
  const main = useRef<HTMLElement>(null);
  const logoutAction = useAction();
  const signedOut = useCallback(() => {
    setCsrfToken('');
    setAccount(null);
    setMonitors([]);
    setWebhooks([]);
    setRecovery('');
    setDataError('');
  }, []);
  async function bootstrap() {
    setBootError('');
    setBooting(true);
    try {
      const settings = await api<ProductConfig>('/v1/config');
      setConfig(settings);
      document.title = settings.product_name;
      try {
        const identity = await api<AccountResponse>('/v1/account');
        setCsrfToken(identity.csrf_token);
        setAccount(identity.account);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
      }
    } catch (error) {
      setBootError(message(error));
    } finally {
      setBooting(false);
    }
  }
  useEffect(() => {
    void bootstrap();
  }, []);
  useEffect(() => {
    const change = () => {
      setView(currentView());
      main.current?.focus();
    };
    window.addEventListener('hashchange', change);
    window.addEventListener('session-expired', signedOut);
    return () => {
      window.removeEventListener('hashchange', change);
      window.removeEventListener('session-expired', signedOut);
    };
  }, [signedOut]);
  const refresh = useCallback(async () => {
    if (!account || loading.current) return;
    loading.current = true;
    setRefreshing(true);
    const results = await Promise.allSettled([
      api<Page<Monitor>>('/v1/monitors?limit=100'),
      api<Page<Webhook>>('/v1/webhooks?limit=100'),
    ]);
    if (results[0].status === 'fulfilled') setMonitors(results[0].value.items);
    if (results[1].status === 'fulfilled') setWebhooks(results[1].value.items);
    const failed = results.find((result) => result.status === 'rejected');
    setDataError(failed?.status === 'rejected' ? message(failed.reason) : '');
    loading.current = false;
    setRefreshing(false);
  }, [account]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, 60000);
    return () => clearInterval(timer);
  }, [refresh]);
  if (booting)
    return (
      <main className="loading-screen">
        <span className="spinner" />
        <p>Getting your flights ready…</p>
      </main>
    );
  if (bootError || !config)
    return (
      <main className="loading-screen">
        <h1>We couldn’t load the dashboard</h1>
        <Notice danger>{bootError || 'Configuration is unavailable.'}</Notice>
        <Button onClick={() => void bootstrap()}>Try again</Button>
      </main>
    );
  if (!account)
    return (
      <Auth
        config={config}
        onSignedIn={(result) => {
          setAccount(result.account);
          setCsrfToken(result.csrf_token);
          setRecovery(result.recovery_code ?? '');
          setView(currentView());
        }}
      />
    );
  const authorization = new URLSearchParams(location.search).get('authorize');
  return (
    <div className="app-layout">
      <a
        href="#main-content"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault();
          main.current?.focus();
        }}
      >
        Skip to main content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#monitors">
          <span className="brand-mark">
            <Icon name="plane" size={23} />
          </span>
          {config.product_name}
        </a>
        <div className="workspace-label">Your workspace</div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              aria-current={!authorization && view === item.id ? 'page' : undefined}
            >
              <Icon name={item.icon} size={19} />
              <span>{item.label}</span>
              {item.id === 'monitors' && (
                <span className="nav-count">
                  {
                    monitors.filter((item) => !['cancelled', 'expired'].includes(item.status))
                      .length
                  }
                </span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Icon name="shield" size={19} />
            <p>
              A small tool for
              <br />
              <strong>better-timed decisions.</strong>
            </p>
          </div>
          <div className="profile">
            <span className="avatar" aria-hidden="true">
              {account.username.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{account.username}</strong>
              <span>Development account</span>
            </div>
          </div>
          <Button
            kind="ghost"
            busy={logoutAction.busy}
            onClick={() =>
              void logoutAction.run(async () => {
                await api('/auth/logout', { method: 'POST' });
                signedOut();
              })
            }
          >
            Sign out
          </Button>
          {logoutAction.error && <Notice danger>{logoutAction.error}</Notice>}
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="breadcrumb">
            Workspace <span>/</span>{' '}
            {authorization
              ? 'Connect application'
              : navigation.find((item) => item.id === view)?.label}
          </span>
          {!config.billing_enabled && (
            <span className="free-badge">
              <span className="status-dot" />
              Free during development
            </span>
          )}
          <Button
            kind="ghost"
            aria-label="Refresh dashboard"
            busy={refreshing}
            onClick={() => void refresh()}
          >
            <Icon name="refresh" size={18} />
          </Button>
        </header>
        <main className="main-content" id="main-content" tabIndex={-1} ref={main}>
          {recovery && (
            <Secret
              title="Your account recovery code"
              value={recovery}
              onDismiss={() => setRecovery('')}
            >
              Save this code in a password manager. It is the way to recover your account if you
              forget your password, and it is shown only once.
            </Secret>
          )}
          {dataError && (
            <Notice danger>
              {dataError}{' '}
              <button className="text-button" onClick={() => void refresh()}>
                Retry
              </button>
            </Notice>
          )}
          {authorization ? (
            <Consent id={authorization} />
          ) : view === 'alerts' ? (
            <Alerts monitors={monitors} />
          ) : view === 'webhooks' ? (
            <Webhooks items={webhooks} refresh={refresh} />
          ) : view === 'developer' ? (
            <Developer config={config} />
          ) : view === 'settings' ? (
            <Settings account={account} onSignedOut={signedOut} />
          ) : (
            <Monitors
              items={monitors}
              webhooks={webhooks}
              config={config}
              refresh={refresh}
              loading={refreshing}
            />
          )}
        </main>
        <footer className="workspace-footer">
          <span>{config.product_name} · Free development preview</span>
          <span>Made for a better time to book.</span>
        </footer>
      </div>
    </div>
  );
}
