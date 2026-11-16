import { createHmac, timingSafeEqual } from 'node:crypto';

export const ADMIN_COOKIE = 'aster_admin';
const MAX_AGE_SECONDS = 8 * 60 * 60;

function sessionSecret() {
  return process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_PASSWORD || '';
}

export function adminConfigured() {
  return Boolean(process.env.ADMIN_PASSWORD);
}

export function checkPassword(input) {
  const expected = process.env.ADMIN_PASSWORD || '';
  if (!expected) return false;
  const supplied = Buffer.from(String(input ?? ''), 'utf8');
  const wanted = Buffer.from(expected, 'utf8');
  if (supplied.length !== wanted.length) return false;
  return timingSafeEqual(supplied, wanted);
}

export function issueToken() {
  const exp = Math.floor(Date.now() / 1000) + MAX_AGE_SECONDS;
  const payload = Buffer.from(JSON.stringify({ exp }), 'utf8').toString('base64url');
  const signature = createHmac('sha256', sessionSecret()).update(payload).digest('base64url');
  return `${payload}.${signature}`;
}

export function verifyToken(token) {
  if (typeof token !== 'string') return false;
  const parts = token.split('.');
  if (parts.length !== 2) return false;
  const [payload, signature] = parts;
  if (!payload || !signature) return false;
  const expected = createHmac('sha256', sessionSecret()).update(payload).digest('base64url');
  const suppliedBuffer = Buffer.from(signature, 'utf8');
  const expectedBuffer = Buffer.from(expected, 'utf8');
  if (suppliedBuffer.length !== expectedBuffer.length) return false;
  if (!timingSafeEqual(suppliedBuffer, expectedBuffer)) return false;
  try {
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return Number(data.exp) > Date.now() / 1000;
  } catch {
    return false;
  }
}

export function parseCookies(header = '') {
  const cookies = {};
  for (const pair of String(header).split(';')) {
    const index = pair.indexOf('=');
    if (index < 0) continue;
    const key = pair.slice(0, index).trim();
    if (!key) continue;
    const value = pair.slice(index + 1).trim();
    try {
      cookies[key] = decodeURIComponent(value);
    } catch {
      cookies[key] = value;
    }
  }
  return cookies;
}

export function getToken(req) {
  return parseCookies(req.headers.cookie)[ADMIN_COOKIE];
}

function secureCookies() {
  return process.env.NODE_ENV === 'production' || process.env.COOKIE_SECURE === 'true';
}

export function setSessionCookie(res, token) {
  res.cookie(ADMIN_COOKIE, token, {
    httpOnly: true,
    sameSite: 'strict',
    secure: secureCookies(),
    maxAge: MAX_AGE_SECONDS * 1000,
    path: '/',
  });
}

export function clearSessionCookie(res) {
  res.clearCookie(ADMIN_COOKIE, {
    httpOnly: true,
    sameSite: 'strict',
    secure: secureCookies(),
    path: '/',
  });
}

export function requireAdmin(req, res, next) {
  if (!adminConfigured()) {
    return res.status(503).json({ ok: false, error: 'admin_not_configured' });
  }
  if (!verifyToken(getToken(req))) {
    return res.status(401).json({ ok: false, error: 'authentication_required' });
  }
  return next();
}
