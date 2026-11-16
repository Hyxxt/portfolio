export function createRateLimiter({ windowMs, max, name = 'limit' }) {
  const entries = new Map();
  let lastCleanup = Date.now();

  return function take(key) {
    const now = Date.now();
    if (now - lastCleanup > windowMs) {
      for (const [entryKey, entry] of entries) {
        if (entry.reset <= now) entries.delete(entryKey);
      }
      lastCleanup = now;
    }

    const safeKey = `${name}:${key}`;
    let entry = entries.get(safeKey);
    if (!entry || entry.reset <= now) {
      entry = { count: 0, reset: now + windowMs };
      entries.set(safeKey, entry);
    }
    entry.count += 1;

    return {
      ok: entry.count <= max,
      remaining: Math.max(0, max - entry.count),
      retryAfter: Math.max(1, Math.ceil((entry.reset - now) / 1000)),
    };
  };
}
