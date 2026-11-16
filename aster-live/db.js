import pg from 'pg';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const STATUSES = ['new', 'contacted', 'closed'];

function makeReference() {
  const now = new Date();
  const date = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  return `AST-${date}-${randomBytes(3).toString('hex').toUpperCase()}`;
}

function mapPgRow(row) {
  let items = row.items;
  if (typeof items === 'string') {
    try {
      items = JSON.parse(items);
    } catch {
      items = [];
    }
  }
  if (!Array.isArray(items)) items = [];
  return {
    id: row.id,
    reference: row.reference,
    name: row.name,
    email: row.email,
    company: row.company,
    country: row.country,
    quantity: row.quantity,
    message: row.message,
    items,
    status: row.status,
    source_ip: row.source_ip,
    user_agent: row.user_agent,
    created_at: new Date(row.created_at).toISOString(),
  };
}

async function createPgStore(connectionString) {
  const useSsl = process.env.PGSSL === 'disable'
    ? false
    : process.env.PGSSL === 'require'
      || /sslmode=require/i.test(connectionString)
      || /\.render\.com(?::\d+)?\//i.test(connectionString);
  const pool = new pg.Pool({
    connectionString,
    max: 5,
    ssl: useSsl ? { rejectUnauthorized: false } : false,
  });
  pool.on('error', (error) => console.error('postgres pool error:', error.message));

  await pool.query(`
    CREATE TABLE IF NOT EXISTS rfqs (
      id uuid PRIMARY KEY,
      reference text UNIQUE NOT NULL,
      name text NOT NULL,
      email text NOT NULL,
      company text NOT NULL,
      country text NOT NULL,
      quantity integer NOT NULL,
      message text NOT NULL,
      items jsonb NOT NULL DEFAULT '[]'::jsonb,
      status text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'contacted', 'closed')),
      source_ip text,
      user_agent text,
      created_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await pool.query('CREATE INDEX IF NOT EXISTS rfqs_created_at_idx ON rfqs (created_at DESC)');
  await pool.query('CREATE INDEX IF NOT EXISTS rfqs_status_idx ON rfqs (status)');

  async function insert(record) {
    const { rows } = await pool.query(
      `INSERT INTO rfqs
        (id, reference, name, email, company, country, quantity, message, items, source_ip, user_agent)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
       RETURNING *`,
      [
        record.id,
        record.reference,
        record.name,
        record.email,
        record.company,
        record.country,
        record.quantity,
        record.message,
        JSON.stringify(record.items),
        record.source_ip,
        record.user_agent,
      ],
    );
    return mapPgRow(rows[0]);
  }

  return {
    kind: 'postgres',
    async createRfq(input) {
      let lastError;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        const record = { ...input, id: randomUUID(), reference: makeReference() };
        try {
          return await insert(record);
        } catch (error) {
          lastError = error;
          if (error.code !== '23505') throw error;
        }
      }
      throw lastError;
    },
    async listRfqs({ status, limit = 100, offset = 0 } = {}) {
      const safeLimit = Math.min(Math.max(Number(limit) || 100, 1), 200);
      const safeOffset = Math.max(Number(offset) || 0, 0);
      const values = [];
      let where = '';
      if (STATUSES.includes(status)) {
        values.push(status);
        where = `WHERE status = $${values.length}`;
      }
      values.push(safeLimit, safeOffset);
      const { rows } = await pool.query(
        `SELECT * FROM rfqs ${where} ORDER BY created_at DESC LIMIT $${values.length - 1} OFFSET $${values.length}`,
        values,
      );
      return rows.map(mapPgRow);
    },
    async getStats() {
      const { rows } = await pool.query('SELECT status, COUNT(*)::int AS count FROM rfqs GROUP BY status');
      const counts = { new: 0, contacted: 0, closed: 0 };
      for (const row of rows) counts[row.status] = row.count;
      return { total: counts.new + counts.contacted + counts.closed, ...counts };
    },
    async updateStatus(id, status) {
      const { rows } = await pool.query(
        'UPDATE rfqs SET status = $1 WHERE id = $2 RETURNING *',
        [status, id],
      );
      return rows[0] ? mapPgRow(rows[0]) : null;
    },
    async deleteRfq(id) {
      const { rowCount } = await pool.query('DELETE FROM rfqs WHERE id = $1', [id]);
      return rowCount > 0;
    },
    async close() {
      await pool.end();
    },
  };
}

async function createJsonStore(file) {
  const absolute = path.resolve(file);
  await mkdir(path.dirname(absolute), { recursive: true });

  async function readAll() {
    try {
      const text = await readFile(absolute, 'utf8');
      const parsed = JSON.parse(text);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      if (error.code === 'ENOENT') return [];
      throw error;
    }
  }

  async function writeAll(rows) {
    const temp = `${absolute}.${process.pid}.tmp`;
    await writeFile(temp, JSON.stringify(rows, null, 2), { encoding: 'utf8', mode: 0o600 });
    await rename(temp, absolute);
  }

  let queue = Promise.resolve();
  function withLock(fn) {
    const run = queue.then(fn, fn);
    queue = run.catch(() => {});
    return run;
  }

  return {
    kind: 'json',
    createRfq(input) {
      return withLock(async () => {
        const rows = await readAll();
        let reference = makeReference();
        while (rows.some((row) => row.reference === reference)) reference = makeReference();
        const record = {
          ...input,
          id: randomUUID(),
          reference,
          status: 'new',
          created_at: new Date().toISOString(),
        };
        rows.unshift(record);
        await writeAll(rows);
        return record;
      });
    },
    async listRfqs({ status, limit = 100, offset = 0 } = {}) {
      const rows = await readAll();
      const safeLimit = Math.min(Math.max(Number(limit) || 100, 1), 200);
      const safeOffset = Math.max(Number(offset) || 0, 0);
      return rows
        .filter((row) => !STATUSES.includes(status) || row.status === status)
        .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
        .slice(safeOffset, safeOffset + safeLimit);
    },
    async getStats() {
      const rows = await readAll();
      const counts = { new: 0, contacted: 0, closed: 0 };
      for (const row of rows) counts[row.status] = (counts[row.status] || 0) + 1;
      return { total: rows.length, ...counts };
    },
    updateStatus(id, status) {
      return withLock(async () => {
        const rows = await readAll();
        const row = rows.find((item) => item.id === id);
        if (!row) return null;
        row.status = status;
        await writeAll(rows);
        return row;
      });
    },
    deleteRfq(id) {
      return withLock(async () => {
        const rows = await readAll();
        const next = rows.filter((row) => row.id !== id);
        if (next.length === rows.length) return false;
        await writeAll(next);
        return true;
      });
    },
    async close() {},
  };
}

export async function createStore() {
  if (process.env.DATABASE_URL) return createPgStore(process.env.DATABASE_URL);
  if (process.env.NODE_ENV === 'production') {
    throw new Error('DATABASE_URL is required when NODE_ENV=production');
  }
  return createJsonStore(process.env.DATA_FILE || './data/rfqs.json');
}
