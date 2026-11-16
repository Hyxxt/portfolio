import express from 'express';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createStore, STATUSES } from './db.js';
import {
  adminConfigured,
  checkPassword,
  clearSessionCookie,
  getToken,
  issueToken,
  requireAdmin,
  setSessionCookie,
  verifyToken,
} from './auth.js';
import { validateRfq } from './validate.js';
import { createRateLimiter } from './rate-limit.js';
import { notifyNewRfq } from './notify.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);

function allowedOrigins() {
  return new Set(
    String(process.env.ALLOWED_ORIGINS || 'https://northform-ckeb.onrender.com')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean),
  );
}

function sameOrigin(req, res, next) {
  const origin = req.get('origin');
  if (!origin) return next();
  try {
    if (new URL(origin).host === req.get('host')) return next();
  } catch {
    // Fall through to rejection.
  }
  return res.status(403).json({ ok: false, error: 'origin_not_allowed' });
}

function csvCell(value) {
  let text = String(value ?? '');
  // Prevent spreadsheet formula injection from user-controlled text.
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function makeCsv(rows) {
  const header = [
    'Reference',
    'Created',
    'Status',
    'Name',
    'Email',
    'Company',
    'Country',
    'Quantity',
    'Shortlist',
    'Requirements',
  ];
  const lines = [
    header,
    ...rows.map((row) => [
      row.reference,
      row.created_at,
      row.status,
      row.name,
      row.email,
      row.company,
      row.country,
      row.quantity,
      (row.items || []).join(', '),
      row.message,
    ]),
  ];
  return `﻿${lines.map((line) => line.map(csvCell).join(',')).join('\r\n')}`;
}

export async function createApp({ store: suppliedStore } = {}) {
  if (process.env.NODE_ENV === 'production' && !process.env.ADMIN_PASSWORD) {
    throw new Error('ADMIN_PASSWORD is required when NODE_ENV=production');
  }

  const store = suppliedStore || await createStore();
  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', 1);
  app.locals.store = store;

  const rfqLimiter = createRateLimiter({ windowMs: 10 * 60 * 1000, max: 12, name: 'rfq' });
  const loginLimiter = createRateLimiter({ windowMs: 15 * 60 * 1000, max: 6, name: 'login' });
  const origins = allowedOrigins();

  app.use((req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    if (req.path.startsWith('/api/')) {
      res.setHeader('Cache-Control', 'no-store');
    } else {
      // Mirrors the original site's _headers and lets the WordPress
      // Playground iframe fetch the theme/plugin zips.
      res.setHeader('Access-Control-Allow-Origin', '*');
    }
    next();
  });

  app.use(express.json({ limit: '32kb' }));

  app.use((req, res, next) => {
    const started = Date.now();
    res.on('finish', () => {
      if (req.path.startsWith('/api/')) {
        console.log(`${req.method} ${req.path} ${res.statusCode} ${Date.now() - started}ms`);
      }
    });
    next();
  });

  app.use('/api/rfq', (req, res, next) => {
    const origin = req.get('origin');
    if (origin && origins.has(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
      res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
      res.setHeader('Access-Control-Max-Age', '600');
    }
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    return next();
  });

  app.get('/api/health', (req, res) => {
    res.json({ ok: true });
  });

  app.post('/api/rfq', async (req, res, next) => {
    try {
      const ip = String(req.ip || req.socket.remoteAddress || 'unknown').slice(0, 64);

      const limit = rfqLimiter(ip);
      if (!limit.ok) {
        res.setHeader('Retry-After', String(limit.retryAfter));
        return res.status(429).json({
          ok: false,
          error: 'too_many_requests',
          message: 'Too many submissions. Please try again later.',
        });
      }

      const body = req.body && typeof req.body === 'object' ? req.body : {};

      // Honeypot: return a normal-looking response and store nothing.
      if (String(body.website || '').trim() !== '') {
        return res.status(201).json({ ok: true, reference: 'AST-DEMO', demo: true });
      }

      const validated = validateRfq(body);
      if (!validated.ok) {
        return res.status(400).json({
          ok: false,
          error: 'validation_failed',
          errors: validated.errors,
        });
      }

      const record = await store.createRfq({
        ...validated.value,
        source_ip: ip,
        user_agent: String(req.get('user-agent') || '').slice(0, 300),
      });

      notifyNewRfq(record).catch((error) => {
        console.error('email notification failed:', error.message);
      });

      return res.status(201).json({
        ok: true,
        reference: record.reference,
        created_at: record.created_at,
      });
    } catch (error) {
      return next(error);
    }
  });

  app.post('/api/admin/login', sameOrigin, (req, res) => {
    if (!adminConfigured()) {
      return res.status(503).json({ ok: false, error: 'admin_not_configured' });
    }
    const ip = String(req.ip || req.socket.remoteAddress || 'unknown').slice(0, 64);
    const limit = loginLimiter(ip);
    if (!limit.ok) {
      res.setHeader('Retry-After', String(limit.retryAfter));
      return res.status(429).json({ ok: false, error: 'too_many_attempts' });
    }
    if (!checkPassword(req.body?.password)) {
      return res.status(401).json({ ok: false, error: 'invalid_password' });
    }
    setSessionCookie(res, issueToken());
    return res.json({ ok: true });
  });

  app.post('/api/admin/logout', sameOrigin, (req, res) => {
    clearSessionCookie(res);
    res.json({ ok: true });
  });

  app.get('/api/admin/me', (req, res) => {
    res.json({
      ok: true,
      configured: adminConfigured(),
      authenticated: adminConfigured() && verifyToken(getToken(req)),
    });
  });

  app.get('/api/admin/rfqs', requireAdmin, async (req, res, next) => {
    try {
      const status = STATUSES.includes(req.query.status) ? req.query.status : undefined;
      const [rfqs, stats] = await Promise.all([
        store.listRfqs({ status, limit: 200, offset: 0 }),
        store.getStats(),
      ]);
      res.json({ ok: true, rfqs, stats });
    } catch (error) {
      next(error);
    }
  });

  app.patch('/api/admin/rfqs/:id', requireAdmin, sameOrigin, async (req, res, next) => {
    try {
      if (!STATUSES.includes(req.body?.status)) {
        return res.status(400).json({ ok: false, error: 'invalid_status' });
      }
      const updated = await store.updateStatus(String(req.params.id), req.body.status);
      if (!updated) return res.status(404).json({ ok: false, error: 'not_found' });
      return res.json({ ok: true, rfq: updated });
    } catch (error) {
      return next(error);
    }
  });

  app.delete('/api/admin/rfqs/:id', requireAdmin, sameOrigin, async (req, res, next) => {
    try {
      const removed = await store.deleteRfq(String(req.params.id));
      if (!removed) return res.status(404).json({ ok: false, error: 'not_found' });
      return res.json({ ok: true });
    } catch (error) {
      return next(error);
    }
  });

  app.get('/api/admin/export.csv', requireAdmin, async (req, res, next) => {
    try {
      const rows = await store.listRfqs({ limit: 200, offset: 0 });
      res.type('text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', 'attachment; filename="northform-rfqs.csv"');
      res.send(makeCsv(rows));
    } catch (error) {
      next(error);
    }
  });

  app.get(['/admin', '/admin/'], (req, res) => {
    res.setHeader('X-Robots-Tag', 'noindex, nofollow');
    res.sendFile(path.join(__dirname, 'admin.html'));
  });

  app.use(express.static(path.join(__dirname, 'public'), {
    extensions: ['html'],
    setHeaders(res, filePath) {
      if (filePath.endsWith('.html')) {
        res.setHeader('Cache-Control', 'no-cache');
      } else {
        res.setHeader('Cache-Control', 'public, max-age=3600');
      }
    },
  }));

  app.use((req, res) => {
    if (req.path.startsWith('/api/')) {
      return res.status(404).json({ ok: false, error: 'not_found' });
    }
    return res.status(404).type('html').send(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Not found · Northform Precision</title>
<style>body{margin:0;background:#f4f2ea;color:#173038;font:16px/1.7 Arial,sans-serif;display:grid;place-items:center;min-height:100vh}.box{max-width:520px;padding:40px}.a{color:#b8683e}</style>
</head><body><div class="box"><p>404</p><h1>That page is not here.</h1>
<p><a class="a" href="/">Return to the Northform demo</a></p></div></body></html>`);
  });

  app.use((error, req, res, next) => {
    if (res.headersSent) return next(error);
    if (error?.type === 'entity.parse.failed' || error?.type === 'entity.too.large') {
      return res.status(400).json({ ok: false, error: 'invalid_request' });
    }
    console.error('request failed:', error);
    if (req.path.startsWith('/api/')) {
      return res.status(500).json({ ok: false, error: 'server_error' });
    }
    return res.status(500).type('text').send('Server error');
  });

  return app;
}

export async function start() {
  const app = await createApp();
  const server = app.listen(PORT, () => {
    console.log(`Northform live listening on http://localhost:${PORT}`);
    console.log(`Admin dashboard: http://localhost:${PORT}/admin`);
    if (!adminConfigured()) console.warn('ADMIN_PASSWORD is not set; the admin dashboard is disabled.');
  });

  let closing = false;
  async function shutdown(signal) {
    if (closing) return;
    closing = true;
    console.log(`Received ${signal}; shutting down.`);
    server.close(async () => {
      await app.locals.store.close();
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10_000).unref();
  }

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
  return server;
}

const isMain = process.argv[1]
  && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;

if (isMain) {
  start().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
