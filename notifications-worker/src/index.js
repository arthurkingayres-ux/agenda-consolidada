// Web Push via Web Crypto API — sem dependências npm
// RFC 8291 (message encryption) + RFC 8292 (VAPID)

function b64u(buf) {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let str = '';
  for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function fromb64u(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  s += '='.repeat((4 - s.length % 4) % 4);
  return Uint8Array.from(atob(s), c => c.charCodeAt(0));
}

function concat(...arrays) {
  const total = arrays.reduce((n, a) => n + a.length, 0);
  const out = new Uint8Array(total);
  let i = 0;
  for (const a of arrays) { out.set(a, i); i += a.length; }
  return out;
}

async function hmac256(key, data) {
  const k = await crypto.subtle.importKey('raw', key, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', k, data));
}

async function hkdfExpand(prk, info, len) {
  return (await hmac256(prk, concat(info, new Uint8Array([1])))).slice(0, len);
}

async function sendPush(subscription, payloadObj, vapidPublicKey, vapidPrivateKey, vapidSubject) {
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payloadObj));

  // ── Encrypt payload (RFC 8291 + RFC 8188 aes128gcm) ──────────────────────
  const authSecret    = fromb64u(subscription.keys.auth);
  const receiverPubRaw = fromb64u(subscription.keys.p256dh);

  const receiverPub = await crypto.subtle.importKey(
    'raw', receiverPubRaw, { name: 'ECDH', namedCurve: 'P-256' }, true, []
  );
  const senderPair = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']
  );
  const senderPubRaw = new Uint8Array(await crypto.subtle.exportKey('raw', senderPair.publicKey));

  const ecdhSecret = new Uint8Array(await crypto.subtle.deriveBits(
    { name: 'ECDH', public: receiverPub }, senderPair.privateKey, 256
  ));

  // PRK_key = HMAC(auth_secret, ecdh_secret)
  const prkKey = await hmac256(authSecret, ecdhSecret);

  // IKM = HKDF-Expand(PRK_key, "WebPush: info\0" || receiver_pub || sender_pub, 32)
  const ikm = await hkdfExpand(
    prkKey,
    concat(new TextEncoder().encode('WebPush: info\x00'), receiverPubRaw, senderPubRaw),
    32
  );

  const salt = crypto.getRandomValues(new Uint8Array(16));

  // PRK = HMAC(salt, IKM)
  const prk = await hmac256(salt, ikm);

  // CEK (16 bytes) e NONCE (12 bytes)
  const cek   = await hkdfExpand(prk, new TextEncoder().encode('Content-Encoding: aes128gcm\x00'), 16);
  const nonce = await hkdfExpand(prk, new TextEncoder().encode('Content-Encoding: nonce\x00'), 12);

  const aesKey = await crypto.subtle.importKey('raw', cek, { name: 'AES-GCM' }, false, ['encrypt']);
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce },
    aesKey,
    concat(payloadBytes, new Uint8Array([2])) // 0x02 = last-record delimiter
  ));

  // RFC 8188 header: salt(16) || rs(4 BE) || idlen(1) || sender_pub(65)
  const header = new Uint8Array(21 + senderPubRaw.length);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, 4096, false);
  header[20] = senderPubRaw.length;
  header.set(senderPubRaw, 21);

  const body = concat(header, ciphertext);

  // ── VAPID JWT (RFC 8292) ──────────────────────────────────────────────────
  const pubBytes = fromb64u(vapidPublicKey); // 65 bytes: 0x04 || x(32) || y(32)
  const privBytes = fromb64u(vapidPrivateKey); // 32 bytes

  const signingKey = await crypto.subtle.importKey(
    'jwk',
    {
      kty: 'EC', crv: 'P-256',
      x: b64u(pubBytes.slice(1, 33)),
      y: b64u(pubBytes.slice(33, 65)),
      d: b64u(privBytes),
      key_ops: ['sign']
    },
    { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']
  );

  const audience = new URL(subscription.endpoint).origin;
  const exp = Math.floor(Date.now() / 1000) + 12 * 3600;
  const jwtHead = b64u(new TextEncoder().encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const jwtBody = b64u(new TextEncoder().encode(JSON.stringify({ aud: audience, exp, sub: vapidSubject })));
  const unsigned = `${jwtHead}.${jwtBody}`;

  const rawSig = new Uint8Array(await crypto.subtle.sign(
    { name: 'ECDSA', hash: { name: 'SHA-256' } }, signingKey,
    new TextEncoder().encode(unsigned)
  ));
  const jwt = `${unsigned}.${b64u(rawSig)}`;

  return fetch(subscription.endpoint, {
    method: 'POST',
    headers: {
      'Authorization': `vapid t=${jwt},k=${vapidPublicKey}`,
      'Content-Type': 'application/octet-stream',
      'Content-Encoding': 'aes128gcm',
      'TTL': '86400',
    },
    body,
  });
}

// ── CORS ─────────────────────────────────────────────────────────────────────
function corsHeaders(origin, allowed) {
  const ok = origin === allowed || origin.startsWith('http://localhost');
  return {
    'Access-Control-Allow-Origin': ok ? origin : '',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

// ── Worker ───────────────────────────────────────────────name───────────────
export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const cors = corsHeaders(origin, env.ALLOWED_ORIGIN || '');

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/subscribe') {
      const { subscription, events } = await request.json();
      const now = Date.now();
      const futureEvents = events.filter(e => new Date(e.isoTime).getTime() > now);
      await env.STORE.put('data', JSON.stringify({ subscription, events: futureEvents }));
      return new Response('OK', { status: 200, headers: cors });
    }

    return new Response('Not Found', { status: 404, headers: cors });
  },

  async scheduled(event, env) {
    const data = await env.STORE.get('data', { type: 'json' });
    if (!data?.subscription || !data?.events?.length) return;

    const now = Date.now();

    for (const ev of data.events) {
      const diffH = (new Date(ev.isoTime).getTime() - now) / 3_600_000;

      let notification = null;

      if (diffH >= 23.5 && diffH <= 24.5) {
        const time = new Date(ev.isoTime).toLocaleString('pt-BR', {
          hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo'
        });
        notification = {
          title: '🏥 Plantão HVC — 24h',
          body: `${ev.label} ${ev.hours} · amanhã às ${time}`
        };
      } else if (diffH >= 0.5 && diffH <= 1.5) {
        const time = new Date(ev.isoTime).toLocaleString('pt-BR', {
          hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo'
        });
        notification = {
          title: '🏥 Plantão HVC — 1h',
          body: `${ev.label} ${ev.hours} · começa às ${time}`
        };
      }

      if (!notification) continue;

      try {
        const resp = await sendPush(
          data.subscription, notification,
          env.VAPID_PUBLIC_KEY, env.VAPID_PRIVATE_KEY, env.VAPID_SUBJECT
        );
        if (resp.status === 410) {
          // Subscription expirada — limpar KV
          await env.STORE.delete('data');
          return;
        }
      } catch (err) {
        console.error('Push failed:', err.message);
      }
    }
  }
};
