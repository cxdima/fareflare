/**
 * The browser side of passkeys. The service sends WebAuthn options as JSON with
 * base64url fields; the browser API wants ArrayBuffers, and its answer goes back
 * as JSON again. 1Password, iCloud Keychain and Google Password Manager all take
 * part through these same two calls.
 */

type Json = Record<string, unknown>;
type Descriptor = { id: string; type: 'public-key'; transports?: AuthenticatorTransport[] };

function toBase64url(buffer: ArrayBuffer): string {
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64url(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] {
  return ((list as Descriptor[] | undefined) ?? []).map((item) => ({
    ...item,
    id: fromBase64url(item.id),
  }));
}

export function passkeysSupported(): boolean {
  return typeof window.PublicKeyCredential === 'function' && !!navigator.credentials;
}

/** True when the browser can offer passkeys in the email field's autofill list. */
export async function passkeyAutofillSupported(): Promise<boolean> {
  if (!passkeysSupported()) return false;
  const check = (
    PublicKeyCredential as unknown as { isConditionalMediationAvailable?: () => Promise<boolean> }
  ).isConditionalMediationAvailable;
  return check ? await check().catch(() => false) : false;
}

/** A cancelled or timed-out prompt is the person's choice, not an error to report. */
export function passkeyCancelled(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === 'NotAllowedError' || error.name === 'AbortError')
  );
}

export async function createPasskey(options: Json): Promise<Json> {
  const user = options['user'] as { id: string; name: string; displayName: string };
  const credential = (await navigator.credentials.create({
    publicKey: {
      ...(options as unknown as PublicKeyCredentialCreationOptions),
      challenge: fromBase64url(options['challenge'] as string),
      user: { ...user, id: fromBase64url(user.id) },
      excludeCredentials: descriptors(options['excludeCredentials']),
    },
  })) as PublicKeyCredential | null;
  if (!credential) throw new DOMException('No passkey was created', 'NotAllowedError');
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
  };
}

export async function getPasskey(
  options: Json,
  conditional = false,
  signal?: AbortSignal,
): Promise<Json | null> {
  const credential = (await navigator.credentials.get({
    publicKey: {
      ...(options as unknown as PublicKeyCredentialRequestOptions),
      challenge: fromBase64url(options['challenge'] as string),
      allowCredentials: descriptors(options['allowCredentials']),
    },
    mediation: conditional ? 'conditional' : 'optional',
    signal,
  })) as PublicKeyCredential | null;
  if (!credential) return null;
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      authenticatorData: toBase64url(response.authenticatorData),
      signature: toBase64url(response.signature),
      userHandle: response.userHandle ? toBase64url(response.userHandle) : null,
    },
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
  };
}
