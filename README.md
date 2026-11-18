# Shop CRM

A high-performance Sales Lead Management CRM designed specifically for computer shops and hardware retailers to track leads from walk-ins, phone calls, WhatsApp inquiries, and Meta Lead Ads.

---

## Architecture & Deployment

The production deployment runs behind a host Nginx reverse proxy that terminates TLS on a public domain/subdomain:

```
Internet --> [Host Nginx (TLS / Let's Encrypt)]
               |  (Overwrites X-Forwarded-For: $remote_addr)
               |  (Sets X-Forwarded-Proto: https)
               v
             [Compose Nginx (127.0.0.1:8080)]
               |-- /api/* --> [Django Backend (Gunicorn)]
               +-- /*     --> [Angular SPA static files]
```

### Trusted Proxy Configuration
1. **Host Nginx**: Overwrites `X-Forwarded-For` with `$remote_addr` (`proxy_set_header X-Forwarded-For $remote_addr;`). A reference host configuration is provided in `docs/nginx-host.conf`.
2. **Compose Nginx**: Serves the Angular frontend and reverse-proxies `/api/` to `backend:8000`, passing `$http_x_forwarded_for` through unchanged.
3. **Compose Port Binding**: The Docker Compose Nginx service publishes **strictly** to `127.0.0.1:8080:80` (never `0.0.0.0` or ports 80/443).
4. **Backend Setting**: `NUM_PROXIES=1` ensures DRF and security throttles trust exactly 1 proxy hop (`ips[-1]`).

---

## Getting Started (Development)

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local backend development)
- Node 20+ (for local frontend development, or run via Docker)

### Environment Variables
Copy `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```

Key configuration defaults:
- `DEBUG=False` (safe production default)
- `JWT_COOKIE_SECURE=True` (safe production default; set to `False` only for plain HTTP local dev without SSL)
- `NUM_PROXIES=1`
- `ALLOWED_ORIGINS=http://localhost:8080,https://crm.example.com`

### Creating an Administrator
Superusers must be created interactively through Django's administrative CLI:
```bash
# Inside docker container or local environment:
python backend/manage.py createsuperuser
```

### Demo Data (DEBUG only)
To seed demo stages, users, customers, and leads in a development environment:
```bash
DEBUG=True python backend/manage.py seed_demo
```
*(Note: `seed_demo` automatically aborts with an error if `DEBUG=False`.)*

---

## Database Backups

Nightly database backups should be automated via `cron` on the host using `pg_dump`:

```bash
# Create backup directory
mkdir -p /var/backups/shopcrm

# Run nightly pg_dump via docker exec
docker exec -t shopcrm_db pg_dump -U shopcrm -F c -b -v -f /var/lib/postgresql/data/shopcrm_$(date +\%Y\%m\%d_\%H\%M\%S).dump shopcrm
```

Add to host crontab (`crontab -e`):
```cron
0 2 * * * docker exec -t shopcrm_db pg_dump -U shopcrm -F c shopcrm > /var/backups/shopcrm/shopcrm_$(date +\%Y\%m\%d).dump && find /var/backups/shopcrm/ -type f -name "*.dump" -mtime +14 -delete
```

---

## Verifying OpenAPI Schema

To ensure the committed OpenAPI schema (`schema.yml`) remains synchronized with the backend code:

```bash
./scripts/check_schema.sh
```
