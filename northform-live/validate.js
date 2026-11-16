const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CONTROL_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;

function cleanLine(value, max) {
  return String(value ?? '')
    .replace(CONTROL_RE, ' ')
    .replace(/[\r\n\t]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, max);
}

function cleanText(value, max) {
  return String(value ?? '')
    .replace(CONTROL_RE, '')
    .replace(/\r\n/g, '\n')
    .trim()
    .slice(0, max);
}

function truthyConsent(value) {
  return value === true || value === 'true' || value === '1' || value === 'on' || value === 1;
}

export function validateRfq(body) {
  const input = body && typeof body === 'object' ? body : {};
  const errors = {};

  const name = cleanLine(input.name, 80);
  const email = cleanLine(input.email, 160);
  const company = cleanLine(input.company, 120);
  const country = cleanLine(input.country, 80);
  const message = cleanText(input.message, 3000);
  const quantity = Number(input.quantity);

  if (name.length < 2) errors.name = 'Please enter your name.';
  if (company.length < 2) errors.company = 'Please enter your company name.';
  if (country.length < 2) errors.country = 'Please enter a destination country.';
  if (!EMAIL_RE.test(email)) errors.email = 'Please enter a valid work email.';
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 1000000) {
    errors.quantity = 'Enter a whole quantity between 1 and 1,000,000.';
  }
  if (message.length < 10) errors.message = 'Please describe the requirements in at least 10 characters.';
  if (!truthyConsent(input.consent)) errors.consent = 'Please confirm the demo privacy notice.';

  let items = input.items;
  if (typeof items === 'string') {
    try {
      items = JSON.parse(items);
    } catch {
      items = [];
    }
  }
  if (!Array.isArray(items)) items = [];
  items = [...new Set(items
    .slice(0, 20)
    .map((item) => {
      if (typeof item === 'string') return cleanLine(item, 40);
      if (item && typeof item === 'object') return cleanLine(item.sku, 40);
      return '';
    })
    .filter(Boolean))]
    .slice(0, 10);

  const value = {
    name,
    email,
    company,
    country,
    quantity,
    message,
    items,
    consent: true,
  };

  return { ok: Object.keys(errors).length === 0, errors, value };
}
