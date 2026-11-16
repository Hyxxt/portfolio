import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createApp } from '../server.js';

let tempDir;
let server;
let base;
let cookie;

before(async () => {
  tempDir = await mkdtemp(path.join(tmpdir(), 'aster-live-'));
  process.env.NODE_ENV = 'test';
  process.env.DATA_FILE = path.join(tempDir, 'rfqs.json');
  process.env.ADMIN_PASSWORD = 'test-password';
  process.env.ALLOWED_ORIGINS = 'https://example.test';
  delete process.env.DATABASE_URL;

  const app = await createApp();
  server = app.listen(0);
  await new Promise((resolve) => server.once('listening', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await rm(tempDir, { recursive: true, force: true });
});

const validRfq = {
  name: 'Alex Chen',
  email: 'alex@example.com',
  company: 'Example Engineering',
  country: 'Germany',
  quantity: '250',
  message: '6061-T6 enclosure, anodized, drawing revision B, target four weeks.',
  consent: true,
  items: ['CNC-AL-001'],
  website: '',
};

test('health endpoint', async () => {
  const response = await fetch(`${base}/api/health`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
});

test('invalid RFQ is rejected', async () => {
  const response = await fetch(`${base}/api/rfq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'A', email: 'bad', quantity: 0, message: 'short' }),
  });
  assert.equal(response.status, 400);
  const body = await response.json();
  assert.equal(body.ok, false);
  assert.ok(body.errors.email);
  assert.ok(body.errors.name);
});

test('valid RFQ is stored and returns a reference', async () => {
  const response = await fetch(`${base}/api/rfq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(validRfq),
  });
  assert.equal(response.status, 201);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.match(body.reference, /^AST-\d{8}-[A-F0-9]{6}$/);
});

test('honeypot returns a fake success and stores nothing', async () => {
  const response = await fetch(`${base}/api/rfq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...validRfq, website: 'https://spam.example' }),
  });
  assert.equal(response.status, 201);
  const body = await response.json();
  assert.equal(body.reference, 'AST-DEMO');
});

test('CORS preflight only allows the configured origin', async () => {
  const allowed = await fetch(`${base}/api/rfq`, {
    method: 'OPTIONS',
    headers: {
      Origin: 'https://example.test',
      'Access-Control-Request-Method': 'POST',
    },
  });
  assert.equal(allowed.status, 204);
  assert.equal(allowed.headers.get('access-control-allow-origin'), 'https://example.test');

  const denied = await fetch(`${base}/api/rfq`, {
    method: 'OPTIONS',
    headers: {
      Origin: 'https://attacker.test',
      'Access-Control-Request-Method': 'POST',
    },
  });
  assert.equal(denied.status, 204);
  assert.equal(denied.headers.get('access-control-allow-origin'), null);
});

test('admin requires a password and lists the stored RFQ', async () => {
  const unauthorized = await fetch(`${base}/api/admin/rfqs`);
  assert.equal(unauthorized.status, 401);

  const wrong = await fetch(`${base}/api/admin/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: 'wrong' }),
  });
  assert.equal(wrong.status, 401);

  const login = await fetch(`${base}/api/admin/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: 'test-password' }),
  });
  assert.equal(login.status, 200);
  const setCookie = login.headers.get('set-cookie');
  assert.ok(setCookie);
  cookie = setCookie.split(';')[0];

  const list = await fetch(`${base}/api/admin/rfqs`, {
    headers: { Cookie: cookie },
  });
  assert.equal(list.status, 200);
  const body = await list.json();
  assert.equal(body.rfqs.length, 1);
  assert.equal(body.rfqs[0].reference.startsWith('AST-'), true);
  assert.equal(body.stats.new, 1);
  assert.equal(body.stats.total, 1);

  const id = body.rfqs[0].id;
  const update = await fetch(`${base}/api/admin/rfqs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Cookie: cookie },
    body: JSON.stringify({ status: 'contacted' }),
  });
  assert.equal(update.status, 200);
  assert.equal((await update.json()).rfq.status, 'contacted');

  const filtered = await fetch(`${base}/api/admin/rfqs?status=contacted`, {
    headers: { Cookie: cookie },
  });
  assert.equal(filtered.status, 200);
  assert.equal((await filtered.json()).rfqs.length, 1);
});

test('admin CSV export includes the stored record', async () => {
  const response = await fetch(`${base}/api/admin/export.csv`, {
    headers: { Cookie: cookie },
  });
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /text\/csv/);
  const buffer = Buffer.from(await response.arrayBuffer());
  assert.deepEqual([...buffer.subarray(0, 3)], [0xef, 0xbb, 0xbf]);
  const text = buffer.toString('utf8').replace(/^﻿/, '');
  assert.match(text, /AST-\d{8}-[A-F0-9]{6}/);
  assert.match(text, /Example Engineering/);
});

test('admin can delete a record', async () => {
  const list = await fetch(`${base}/api/admin/rfqs`, {
    headers: { Cookie: cookie },
  });
  const id = (await list.json()).rfqs[0].id;
  const deleted = await fetch(`${base}/api/admin/rfqs/${id}`, {
    method: 'DELETE',
    headers: { Cookie: cookie },
  });
  assert.equal(deleted.status, 200);
  const afterDelete = await fetch(`${base}/api/admin/rfqs`, {
    headers: { Cookie: cookie },
  });
  assert.equal((await afterDelete.json()).rfqs.length, 0);
});
