import { useEffect, useState, type FormEvent } from 'react';
import { api } from './api';
import type { Account, Page, Preferences } from './types';
import { Button, Dialog, Icon, Notice, useAction } from './ui';

type Telegram = { enabled: boolean; connected: boolean; bot_username?: string };
type Grant = {
  id: string;
  client_name: string;
  created_at: number;
  expires_at: number;
  revoked: boolean;
};

function ConnectedApps() {
  const [grants, setGrants] = useState<Grant[]>([]);
  const [selected, setSelected] = useState<Grant | null>(null);
  const action = useAction();
  async function load() {
    setGrants((await api<Page<Grant>>('/v1/oauth/grants')).items);
  }
  useEffect(() => {
    void action.run(load);
  }, []);
  return (
    <section className="panel">
      <h2>Connected applications</h2>
      <p className="muted">
        Applications you approved through MCP sign-in. Revoke access when you no longer use a
        connection.
      </p>
      {action.error && <Notice danger>{action.error}</Notice>}
      {grants.some((grant) => !grant.revoked) ? (
        <ul className="connection-list">
          {grants
            .filter((grant) => !grant.revoked)
            .map((grant) => (
              <li key={grant.id}>
                <strong>{grant.client_name}</strong>
                <Button onClick={() => setSelected(grant)}>
                  Revoke access<span className="sr-only"> for {grant.client_name}</span>
                </Button>
              </li>
            ))}
        </ul>
      ) : (
        <p className="small-note">
          {action.busy ? 'Loading connected applications…' : 'No connected applications.'}
        </p>
      )}
      {selected && (
        <Dialog title="Revoke application access?" onClose={() => setSelected(null)}>
          <p>
            {selected.client_name} will lose access to your account. You can reconnect it later.
          </p>
          <div className="actions end">
            <Button onClick={() => setSelected(null)}>Keep connection</Button>
            <Button
              kind="danger"
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await api(`/v1/oauth/grants/${selected.id}`, { method: 'DELETE' });
                  setSelected(null);
                  await load();
                })
              }
            >
              Revoke access
            </Button>
          </div>
        </Dialog>
      )}
    </section>
  );
}

function TelegramSettings() {
  const [telegram, setTelegram] = useState<Telegram | null>(null);
  const [url, setUrl] = useState('');
  const action = useAction();
  async function load() {
    setTelegram(await api<Telegram>('/v1/telegram'));
  }
  useEffect(() => {
    void action.run(load);
  }, []);
  return (
    <section className="panel">
      <div className="section-heading">
        <h2>Telegram alerts</h2>
        {telegram && (
          <span className={`status ${telegram.connected ? 'status-active' : 'status-pending'}`}>
            {telegram.connected ? 'Connected' : 'Not connected'}
          </span>
        )}
      </div>
      <p className="muted">
        Connect your Telegram account to receive alerts from monitors without an explicit webhook
        destination.
      </p>
      {action.error && <Notice danger>{action.error}</Notice>}
      {telegram?.enabled === false ? (
        <p>Telegram is not configured on this installation yet.</p>
      ) : telegram?.connected ? (
        <div className="actions">
          <Button
            onClick={() =>
              void action.run(async () => {
                await api('/v1/telegram', { method: 'DELETE' });
                setUrl('');
                await load();
              })
            }
            busy={action.busy}
          >
            Disconnect Telegram
          </Button>
        </div>
      ) : (
        telegram && (
          <div className="actions">
            <Button
              kind="primary"
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  const result = await api<{ url: string }>('/v1/telegram', { method: 'POST' });
                  const parsed = new URL(result.url);
                  if (parsed.protocol !== 'https:' || parsed.hostname !== 't.me')
                    throw new Error('The server returned an invalid Telegram link.');
                  setUrl(parsed.href);
                })
              }
            >
              {url ? 'Create a new connect link' : 'Connect Telegram'}
            </Button>
            {url && (
              <>
                <a className="button secondary" href={url} target="_blank" rel="noreferrer">
                  Open Telegram
                  <Icon name="external" size={16} />
                  <span className="sr-only"> (opens a new tab)</span>
                </a>
                <Button onClick={() => void action.run(load)} busy={action.busy}>
                  Check connection
                </Button>
              </>
            )}
          </div>
        )
      )}
      {url && !telegram?.connected && (
        <p className="small-note">
          Open the link and press Start in Telegram, then check the connection here. This link
          expires shortly.
        </p>
      )}
    </section>
  );
}

export function Settings({ account, onSignedOut }: { account: Account; onSignedOut: () => void }) {
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [routes, setRoutes] = useState('');
  const [saved, setSaved] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState('');
  const action = useAction();
  const deleteAction = useAction();
  useEffect(() => {
    void action.run(async () => {
      const result = await api<Preferences>('/v1/preferences');
      setPreferences(result);
      setRoutes(result.muted_routes.join(', '));
    });
  }, []);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!preferences) return;
    setSaved(false);
    await action.run(async () => {
      const result = await api<Preferences>('/v1/preferences', {
        method: 'PUT',
        body: {
          muted: preferences.muted,
          muted_routes: routes
            .split(',')
            .map((value) => value.trim().toUpperCase())
            .filter(Boolean),
        },
      });
      setPreferences(result);
      setSaved(true);
    });
  }
  async function remove(event: FormEvent) {
    event.preventDefault();
    await deleteAction.run(async () => {
      await api('/v1/account', { method: 'DELETE', body: { password } });
      setPassword('');
      onSignedOut();
    });
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Make it work for you</span>
          <h1>Account settings</h1>
          <p>
            Signed in as <strong>{account.username}</strong>.
          </p>
        </div>
      </div>
      <TelegramSettings />
      <ConnectedApps />
      <section className="panel">
        <h2>Notification preferences</h2>
        <p className="muted">Muting stops outgoing alerts. Price checks and history continue.</p>
        {action.error && <Notice danger>{action.error}</Notice>}
        {saved && <Notice>Notification preferences saved.</Notice>}
        {preferences ? (
          <form onSubmit={save} className="form-stack">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={preferences.muted}
                onChange={(event) => {
                  setPreferences({ ...preferences, muted: event.target.checked });
                  setSaved(false);
                }}
              />
              Mute all notifications
            </label>
            <label>
              Muted routes
              <input
                value={routes}
                placeholder="DEN-DFW, SFO-NRT"
                onChange={(event) => {
                  setRoutes(event.target.value);
                  setSaved(false);
                }}
                aria-describedby="routes-help"
              />
            </label>
            <p className="field-hint" id="routes-help">
              Optional airport pairs, separated by commas. For example: DEN-DFW.
            </p>
            <div>
              <Button type="submit" kind="primary" busy={action.busy}>
                Save preferences
              </Button>
            </div>
          </form>
        ) : (
          <p className="muted">Loading preferences…</p>
        )}
      </section>
      <section className="panel">
        <h2>Account recovery</h2>
        <p>
          Your recovery code was shown when you created or recovered this account. Keep it in a
          password manager. If you lose access, use “Forgot your password?” on the sign-in screen.
        </p>
        <p className="small-note">
          Recovery replaces the old code and invalidates existing sessions and credentials.
        </p>
      </section>
      <section className="panel danger-zone">
        <h2>Delete account</h2>
        <p>
          Stop your monitors and revoke access to your account, API keys, and connected
          applications. This cannot be undone.
        </p>
        <Button kind="danger" onClick={() => setDeleting(true)}>
          Delete my account
        </Button>
      </section>
      {deleting && (
        <Dialog
          title="Delete your account?"
          onClose={() => {
            setDeleting(false);
            setPassword('');
          }}
        >
          <p>Your account access and flight monitoring will end. Enter your password to confirm.</p>
          {deleteAction.error && <Notice danger>{deleteAction.error}</Notice>}
          <form onSubmit={remove} className="form-stack">
            <label>
              Confirm password
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <div className="actions end">
              <Button
                onClick={() => {
                  setDeleting(false);
                  setPassword('');
                }}
              >
                Keep my account
              </Button>
              <Button type="submit" kind="danger" busy={deleteAction.busy}>
                Permanently delete account
              </Button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
