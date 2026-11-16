function buildText(rfq) {
  const items = Array.isArray(rfq.items) && rfq.items.length ? rfq.items.join(', ') : 'None';
  return [
    `New demo RFQ: ${rfq.reference}`,
    '',
    `Name: ${rfq.name}`,
    `Company: ${rfq.company}`,
    `Email: ${rfq.email}`,
    `Country: ${rfq.country}`,
    `Quantity: ${rfq.quantity}`,
    `Shortlist: ${items}`,
    '',
    'Requirements:',
    rfq.message,
    '',
    `Received: ${rfq.created_at}`,
    '',
    'This is a fictional Northform Precision demo inquiry. It is not a real order.',
    'Review it in the admin dashboard. Do not reply to the submitter as a real supplier.',
  ].join('\n');
}

export async function notifyNewRfq(rfq) {
  const apiKey = process.env.RESEND_API_KEY;
  const recipients = String(process.env.NOTIFY_EMAIL || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

  if (!apiKey || recipients.length === 0) {
    return { sent: false, reason: 'not_configured' };
  }

  const response = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: process.env.FROM_EMAIL || 'Northform Demo <onboarding@resend.dev>',
      to: recipients,
      subject: `New Northform demo RFQ ${rfq.reference}`,
      text: buildText(rfq),
    }),
  });

  if (!response.ok) {
    const detail = (await response.text()).slice(0, 300);
    throw new Error(`Resend returned ${response.status}: ${detail}`);
  }

  return { sent: true };
}
