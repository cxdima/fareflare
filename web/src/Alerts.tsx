import { useEffect, useState } from 'react';
import { api, money, timestamp } from './api';
import type { Alert, Monitor, Page } from './types';
import { routeName } from './Monitors';
import { Button, Empty, Notice, Status, reasonLabel, useAction } from './ui';

export function Alerts({ monitors }: { monitors: Monitor[] }) {
  const [items, setItems] = useState<Alert[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const action = useAction();
  async function load(next?: string) {
    const result = await api<Page<Alert>>(
      `/v1/alerts${next ? `?cursor=${encodeURIComponent(next)}` : ''}`,
    );
    setItems((previous) => (next ? [...previous, ...result.items] : result.items));
    setCursor(result.next_cursor);
  }
  useEffect(() => {
    void action.run(() => load());
  }, []);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">Every update, accounted for</span>
          <h1>Alert activity</h1>
          <p>Price events and the status of their delivery.</p>
        </div>
        <Button busy={action.busy} onClick={() => void action.run(() => load())}>
          Refresh alerts
        </Button>
      </div>
      {action.error && <Notice danger>{action.error}</Notice>}
      {items.length ? (
        <div className="panel table-panel">
          <div className="table-scroll">
            <table>
              <caption className="sr-only">Price alerts and delivery status</caption>
              <thead>
                <tr>
                  <th scope="col">Flight / event</th>
                  <th scope="col">Observed total</th>
                  <th scope="col">Delivery</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const monitor = monitors.find((value) => value.id === item.monitor_id);
                  return (
                    <tr key={item.id}>
                      <td>
                        <strong>{monitor ? routeName(monitor) : 'Flight monitor'}</strong>
                        <span className="table-subtext">{reasonLabel(item.reason)}</span>
                        <span className="table-subtext">
                          {timestamp(item.observation.observed_at)}
                        </span>
                      </td>
                      <td>{money(item.observation.amount_minor, item.observation.currency)}</td>
                      <td>
                        <Status value={item.status} />
                        <span className="table-subtext">
                          {item.webhook_id ? 'Webhook' : 'Account destination'} · {item.attempts}{' '}
                          {item.attempts === 1 ? 'attempt' : 'attempts'}
                        </span>
                      </td>
                      <td>
                        {item.status === 'dead_letter' && (
                          <Button
                            busy={action.busy}
                            onClick={() =>
                              void action.run(async () => {
                                await api(`/v1/alerts/${item.id}/retry`, { method: 'POST' });
                                await load();
                              })
                            }
                          >
                            Retry delivery
                            <span className="sr-only">
                              {' '}
                              for {monitor ? routeName(monitor) : item.id}
                            </span>
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {cursor && (
            <div className="panel-footer">
              <Button busy={action.busy} onClick={() => void action.run(() => load(cursor))}>
                Load more alerts
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="panel">
          <Empty title={action.busy ? 'Loading alerts…' : 'A quiet start'} icon="bell">
            Alerts will appear when monitoring starts and your chosen price conditions are met. You
            can review delivery failures and retry them here.
          </Empty>
        </div>
      )}
      <p className="page-note">
        An observed low is the lowest price recorded since your monitor started. Suppressed alerts
        were intentionally skipped because of your account settings or monitor state.
      </p>
    </>
  );
}
