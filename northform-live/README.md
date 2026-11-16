# Northform RFQ inbox

Small Express + PostgreSQL backend for the fictional Northform B2B site.

- Public form: https://northform-ckeb.onrender.com/request-quote/
- Admin: https://northform-live.onrender.com/admin
- API: `POST /api/rfq`
- Table: `northform_rfqs` in the existing Render PostgreSQL database

Configuration is supplied via environment variables; passwords are never committed. The service is a demo inbox: it stores fictional portfolio inquiries, it is not a production CRM.
