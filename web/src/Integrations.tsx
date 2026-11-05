import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, requestKey, timestamp } from './api';
import type { ApiKey, Page, ProductConfig, Webhook } from './types';
import { Button, Dialog, Empty, Icon, Notice, Secret, Status, useAction } from './ui';

function WebhookCard({ item, refresh }: { item: Webhook; refresh: () => Promise<void> }) {
  const action = useAction();
  const [token, setToken] = useState('');
  const [note, setNote] = useState('');
  const [confirmation, setConfirmation] = useState<'disable' | 'delete' | null>(null);
  async function challenge() {
    await action.run(async () => {
      const result = await api<{ delivered: boolean; expires_at: number }>(
        `/v1/webhooks/${item.id}/challenge`,
        { method: 'POST' },
      );
      setNote(
        result.delivered
          ? `Challenge delivered. Copy the verification token from your receiver before ${timestamp(result.expires_at)}.`
          : 'The receiver did not accept the challenge. Check its logs and try again.',
      );
    });
  }
  async function verify(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await api(`/v1/webhooks/${item.id}/verify`, { method: 'POST', body: { token } });
      setToken('');
      setNote('Receiver verified. You can now select it when adding a flight.');
      await refresh();
    });
  }
  async function change() {
    await action.run(async () => {
      await api(`/v1/webhooks/${item.id}${confirmation === 'disable' ? '/disable' : ''}`, {
        method: confirmation === 'disable' ? 'POST' : 'DELETE',
      });
      setConfirmation(null);
      await refresh();
    });
  }
  return (
    <article className="panel integration-card">
      <div className="section-heading">
        <div className="integration-title">
          <span className="route-icon">
            <Icon name="link" />
          </span>
          <h2 className="break-word">{item.url}</h2>
        </div>
        {item.status === 'pending' ? (
          <span className="status status-pending">Awaiting verification</span>
        ) : item.status === 'active' ? (
          <span className="status status-active">Verified</span>
        ) : (
          <Status value={item.status} />
        )}
      </div>
      <p className="muted small">
        Added {timestamp(item.created_at)} · ID <code>{item.id}</code>
      </p>
      {action.error && <Notice danger>{action.error}</Notice>}
      {note && <Notice>{note}</Notice>}
      {(item.status === 'pending' || item.status === 'disabled') && (
        <div className="verify-box">
          <p>
            Send a signed challenge to your receiver, then paste data.token from its request body
            here.
          </p>
          <Button busy={action.busy} onClick={() => void challenge()}>
            Send verification challenge
          </Button>
          <form onSubmit={verify} className="inline-form">
            <label>
              Verification token
              <input
                required
                value={token}
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => setToken(event.target.value)}
              />
            </label>
            <Button type="submit" busy={action.busy} kind="primary">
              Verify receiver
            </Button>
          </form>
        </div>
      )}
      <div className="actions">
        {item.status === 'active' && (
          <Button onClick={() => setConfirmation('disable')}>Disable receiver</Button>
        )}
        {item.status !== 'deleted' && (
          <Button kind="ghost" onClick={() => setConfirmation('delete')}>
            Delete receiver
          </Button>
        )}
      </div>
      {confirmation && (
        <Dialog
          title={`${confirmation === 'disable' ? 'Disable' : 'Delete'} this receiver?`}
          onClose={() => setConfirmation(null)}
        >
          <p>
            New deliveries to this receiver will stop. Existing monitors keep their current
            destination; create a new monitor to use another destination.
          </p>
          <div className="actions end">
            <Button onClick={() => setConfirmation(null)}>Cancel</Button>
            <Button kind="danger" busy={action.busy} onClick={() => void change()}>
              {confirmation === 'disable' ? 'Disable receiver' : 'Delete receiver'}
            </Button>
          </div>
        </Dialog>
      )}
    </article>
  );
}

export function Webhooks({ items, refresh }: { items: Webhook[]; refresh: () => Promise<void> }) {
  const [url, setUrl] = useState('');
  const [secret, setSecret] = useState('');
  const [createdUrl, setCreatedUrl] = useState('');
  const action = useAction();
  const attempt = useRef({ url: '', key: '' });
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      if (attempt.current.url !== url) attempt.current = { url, key: requestKey() };
      const result = await api<Webhook & { signing_secret?: string }>('/v1/webhooks', {
        method: 'POST',
        body: { url },
        key: attempt.current.key,
      });
      if (result.signing_secret) {
        setSecret(result.signing_secret);
        setCreatedUrl(url);
      }
      setUrl('');
      await refresh();
    });
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Keep your systems in the loop</span>
          <h1>Webhooks</h1>
          <p>Send signed price alerts to a receiver you control.</p>
        </div>
      </div>
      {secret && (
        <Secret title="Webhook signing secret" value={secret} onDismiss={() => setSecret('')}>
          Save this secret for {createdUrl}. Your receiver uses it to verify incoming requests. It
          will not be shown again.
        </Secret>
      )}
      <section className="panel">
        <h2>Add a receiver</h2>
        <p className="muted">
          Use a public HTTPS endpoint. You’ll verify ownership before it can receive flight alerts.
        </p>
        {action.error && <Notice danger>{action.error}</Notice>}
        <form onSubmit={submit} className="inline-form">
          <label>
            Receiver URL
            <input
              type="url"
              required
              name="webhook_url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://your-app.example/flight-alerts"
              spellCheck={false}
            />
          </label>
          <Button type="submit" kind="primary" busy={action.busy} disabled={!!secret}>
            <Icon name="plus" size={18} />
            Add receiver
          </Button>
        </form>
      </section>
      <div className="section-heading">
        <h2>Your receivers</h2>
        <span>{items.filter((item) => item.status !== 'deleted').length} registered</span>
      </div>
      {items.filter((item) => item.status !== 'deleted').length ? (
        <div className="monitor-list">
          {items
            .filter((item) => item.status !== 'deleted')
            .map((item) => (
              <WebhookCard key={item.id} item={item} refresh={refresh} />
            ))}
        </div>
      ) : (
        <div className="panel">
          <Empty title="Your alerts, where you need them" icon="link">
            Add your first receiver above. You can connect verified receivers to new flight
            monitors.
          </Empty>
        </div>
      )}
      <section className="info-panel">
        <h3>Receiver checklist</h3>
        <p>
          Verify the Standard Webhooks signature using your signing secret and the raw request body.
          Headers are webhook-id, webhook-timestamp, and webhook-signature. Reject stale requests,
          deduplicate webhook-id, and return 2xx after durable acceptance. Verification requests
          have type webhook.verification and include data.token. See the{' '}
          <a href="/docs" target="_blank" rel="noreferrer">
            API reference<span className="sr-only"> (opens a new tab)</span>
          </a>{' '}
          for endpoint schemas.
        </p>
      </section>
    </>
  );
}

export function Developer({ config }: { config: ProductConfig }) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState('');
  const [secret, setSecret] = useState('');
  const [revoke, setRevoke] = useState<ApiKey | null>(null);
  const action = useAction();
  async function load() {
    const result = await api<Page<ApiKey>>('/v1/api-keys');
    setKeys(result.items);
  }
  useEffect(() => {
    void action.run(load);
  }, []);
  async function create(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const result = await api<{ api_key: string }>('/v1/api-keys', {
        method: 'POST',
        body: { name },
      });
      setSecret(result.api_key);
      setName('');
      await load();
    });
  }
  const mcp = config.mcp_url ?? `${location.origin}/mcp`;
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Build something useful</span>
          <h1>API & MCP</h1>
          <p>Your flight monitors, available to your tools and applications.</p>
        </div>
        <a className="button secondary" href="/docs" target="_blank" rel="noreferrer">
          API reference
          <Icon name="external" size={16} />
          <span className="sr-only"> (opens a new tab)</span>
        </a>
      </div>
      <div className="two-columns">
        <section className="panel">
          <span className="feature-icon">
            <Icon name="code" size={24} />
          </span>
          <h2>Connect an MCP client</h2>
          <p>
            Add this remote server URL to a client that supports Streamable HTTP and OAuth. Follow
            its sign-in flow and review the requested access.
          </p>
          <label>
            Remote MCP server
            <input readOnly value={mcp} onFocus={(event) => event.currentTarget.select()} />
          </label>
          <p className="small-note">
            If your client supports custom headers instead, create an API key below and use{' '}
            <code>Authorization: Bearer YOUR_API_KEY</code>. Never put the key in the URL.
          </p>
        </section>
        <section className="panel">
          <span className="feature-icon">
            <Icon name="key" size={24} />
          </span>
          <h2>Use the HTTP API</h2>
          <p>
            Manage monitors, read observations, and configure delivery from your own app. API keys
            have access to your account’s resources.
          </p>
          <pre>
            <code>{`curl '${location.origin}/v1/monitors' \\\n  -H 'Authorization: Bearer YOUR_API_KEY'`}</code>
          </pre>
          <p className="small-note">
            Keep keys on your server or in your client’s secret store. They are not intended for
            public browser code.
          </p>
        </section>
      </div>
      {secret && <Secret title="Your API key" value={secret} onDismiss={() => setSecret('')} />}
      <section className="panel">
        <h2>Create an API key</h2>
        {action.error && <Notice danger>{action.error}</Notice>}
        <form onSubmit={create} className="inline-form">
          <label>
            Key name
            <input
              required
              maxLength={80}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="My automation"
            />
          </label>
          <Button type="submit" kind="primary" busy={action.busy} disabled={!!secret}>
            <Icon name="plus" size={18} />
            Create key
          </Button>
        </form>
      </section>
      <section className="panel">
        <h2>Your API keys</h2>
        {keys.length ? (
          <div className="table-scroll">
            <table>
              <caption className="sr-only">API keys and their expiration dates</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Expires</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <strong>{key.name || 'API key'}</strong>
                      <span className="table-subtext">{key.id}</span>
                    </td>
                    <td>{timestamp(key.expires_at)}</td>
                    <td>
                      {key.revoked
                        ? 'Revoked'
                        : key.expires_at * 1000 < Date.now()
                          ? 'Expired'
                          : 'Active'}
                    </td>
                    <td>
                      {!key.revoked && (
                        <Button kind="ghost" onClick={() => setRevoke(key)}>
                          Revoke<span className="sr-only"> {key.name || key.id}</span>
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No API keys yet" icon="key">
            Create a key when you’re ready to connect an application.
          </Empty>
        )}
      </section>
      {revoke && (
        <Dialog title="Revoke this API key?" onClose={() => setRevoke(null)}>
          <p>
            Applications using {revoke.name || 'this key'} will immediately lose access. This cannot
            be undone.
          </p>
          <div className="actions end">
            <Button onClick={() => setRevoke(null)}>Cancel</Button>
            <Button
              kind="danger"
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await api(`/v1/api-keys/${revoke.id}`, { method: 'DELETE' });
                  setRevoke(null);
                  await load();
                })
              }
            >
              Revoke key
            </Button>
          </div>
        </Dialog>
      )}
    </>
  );
}
