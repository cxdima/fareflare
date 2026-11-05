import { useState, type FormEvent } from 'react';
import { api, setCsrfToken } from './api';
import type { AccountResponse, ProductConfig } from './types';
import { Button, Icon, Notice, useAction } from './ui';

export function Auth({
  config,
  onSignedIn,
}: {
  config: ProductConfig;
  onSignedIn: (value: AccountResponse) => void;
}) {
  const invited =
    new URLSearchParams(location.hash.split('?')[1] ?? location.search.slice(1)).get('invite') ??
    '';
  const [mode, setMode] = useState<'login' | 'register' | 'recover'>(
    invited ? 'register' : 'login',
  );
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [invite, setInvite] = useState(invited);
  const [recoveryCode, setRecoveryCode] = useState('');
  const action = useAction();
  function changeMode(next: typeof mode) {
    setMode(next);
    action.setError('');
    setPassword('');
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const body =
        mode === 'recover'
          ? { username, recovery_code: recoveryCode, new_password: password }
          : {
              username,
              password,
              ...(mode === 'register' && invite ? { invite_token: invite } : {}),
            };
      const result = await api<AccountResponse>(`/auth/${mode}`, { method: 'POST', body });
      setCsrfToken(result.csrf_token);
      setPassword('');
      setRecoveryCode('');
      setInvite('');
      // Remove an invitation from navigation history after it has been used.
      const authorization = new URLSearchParams(location.search).get('authorize');
      history.replaceState(
        null,
        '',
        location.pathname +
          (authorization ? `?authorize=${encodeURIComponent(authorization)}` : '') +
          '#monitors',
      );
      onSignedIn(result);
    });
  }
  return (
    <div className="auth-layout">
      <section className="auth-story" aria-labelledby="welcome-title">
        <a href="#" className="brand">
          <span className="brand-mark">
            <Icon name="plane" size={23} />
          </span>
          {config.product_name}
        </a>
        <div className="auth-intro">
          <span className="eyebrow light">A better moment to book</span>
          <h1 id="welcome-title">
            Your flight.
            <br />A price worth
            <br />
            <span>coming back for.</span>
          </h1>
          <p>
            Keep an eye on the flights you’ve chosen. We’ll watch for lower prices, so you can get
            on with your day.
          </p>
        </div>
        <ol className="auth-steps">
          <li>
            <span>01</span>
            <div>
              <strong>Bring your flight</strong>
              <p>Paste a Google Flights link with your itinerary selected.</p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>Let us keep watch</strong>
              <p>See the latest observed price and its history.</p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>Catch a lower price</strong>
              <p>Get alerts in your dashboard or your own webhook.</p>
            </div>
          </li>
        </ol>
        <p className="auth-footnote">No Google account connection required.</p>
      </section>
      <main className="auth-main" id="main-content">
        {!config.billing_enabled && (
          <span className="free-badge">
            <Icon name="check" size={14} />
            Free during development
          </span>
        )}
        <div className="auth-card">
          <span className="eyebrow">
            {mode === 'register'
              ? 'A little less checking'
              : mode === 'recover'
                ? 'Get back to your flights'
                : 'Good to see you'}
          </span>
          <h2>
            {mode === 'register'
              ? 'Create your account'
              : mode === 'recover'
                ? 'Recover your account'
                : 'Welcome back'}
          </h2>
          <p>
            {mode === 'register'
              ? `${config.registration_mode === 'invite' ? 'Use your invitation to join. ' : ''}No card needed.`
              : mode === 'recover'
                ? 'Use the recovery code you saved when you signed up.'
                : 'Sign in to check the flights you’re watching.'}
          </p>
          {action.error && <Notice danger>{action.error}</Notice>}
          <form onSubmit={submit} className="form-stack">
            <label>
              Username
              <input
                name="username"
                autoComplete="username"
                required
                minLength={3}
                maxLength={80}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoCapitalize="none"
                spellCheck={false}
              />
            </label>
            {mode === 'register' && config.registration_mode === 'invite' && (
              <label>
                Invitation code
                <input
                  name="invite_token"
                  required
                  autoComplete="off"
                  value={invite}
                  onChange={(event) => setInvite(event.target.value)}
                  spellCheck={false}
                />
              </label>
            )}
            {mode === 'recover' && (
              <label>
                Recovery code
                <input
                  name="recovery_code"
                  required
                  autoComplete="off"
                  value={recoveryCode}
                  onChange={(event) => setRecoveryCode(event.target.value)}
                  spellCheck={false}
                />
              </label>
            )}
            <label>
              {mode === 'recover' ? 'New password' : 'Password'}
              <input
                name="password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={mode === 'login' ? undefined : 15}
                maxLength={128}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-describedby={mode !== 'login' ? 'password-hint' : undefined}
              />
            </label>
            {mode !== 'login' && (
              <p id="password-hint" className="field-hint">
                Use 15–128 characters. A password manager works well.
              </p>
            )}
            <Button kind="primary" type="submit" busy={action.busy}>
              {mode === 'register'
                ? 'Create account'
                : mode === 'recover'
                  ? 'Reset password'
                  : 'Sign in'}
              <Icon name="arrow" size={17} />
            </Button>
          </form>
          <div className="auth-links">
            {mode === 'login' ? (
              <>
                <button className="text-button" onClick={() => changeMode('recover')}>
                  Forgot your password?
                </button>
                {config.registration_mode !== 'closed' && (
                  <p>
                    New here?{' '}
                    <button className="text-button" onClick={() => changeMode('register')}>
                      Create an account
                    </button>
                  </p>
                )}
              </>
            ) : (
              <p>
                Already have an account?{' '}
                <button className="text-button" onClick={() => changeMode('login')}>
                  Sign in
                </button>
              </p>
            )}
          </div>
          <p className="small-note">
            Development access includes {config.limits.monitors} flight monitors. Prices are
            observations, not a booking guarantee.
          </p>
        </div>
      </main>
    </div>
  );
}
