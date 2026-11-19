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
               |-- /api/*    --> [Django Backend (Gunicorn + WhiteNoise)]
               |-- /admin/*  --> [Django Backend (Gunicorn + WhiteNoise, IP Restricted)]
               |-- /static/* --> [Compose Nginx / WhiteNoise]
               +-- /*        --> [Angular SPA static files]
```

### Trusted Proxy Configuration
1. **Host Nginx**: Overwrites `X-Forwarded-For` with `$remote_addr` (`proxy_set_header X-Forwarded-For $remote_addr;`). A reference host configuration is provided in `docs/nginx-host.conf`.
2. **Compose Nginx**: Serves the Angular frontend and reverse-proxies `/api/` to `backend:8000`, passing `$http_x_forwarded_for` through unchanged.
3. **Compose Port Binding**: The Docker Compose Nginx service publishes **strictly** to `127.0.0.1:8080:80` (never `0.0.0.0` or ports 80/443).
4. **Backend Setting**: `NUM_PROXIES=1` ensures DRF and security throttles trust exactly 1 proxy hop (`ips[-1]`).
5. **Admin Endpoint Security**: `/admin/` is restricted at the host Nginx level to localhost SSH tunnels and trusted office IPs only (see `docs/nginx-host.conf`).
6. **Static Files Serving**: Handled by WhiteNoise in Django/Gunicorn and cached at the Nginx layer with long-lived Cache-Control headers.

---

## Getting Started (Development)

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local backend development)
- Node 22+ LTS (for local frontend development, or run via Docker)

### Environment Overrides (`docker-compose.dev.yml`)
Plain `docker compose up` is production-safe by default (no automatic overrides).
For local development where you want `DEBUG=True`, `JWT_COOKIE_SECURE=False`, and `ALLOWED_ORIGINS=http://127.0.0.1:8080,http://localhost:8080`, supply `docker-compose.dev.yml`:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```
In production with TLS behind the host Nginx proxy, deploy strictly using:
```bash
docker compose up -d
```

### Running Frontend via Docker
Always execute Node commands using the host's UID and GID to ensure generated files have correct file permissions:
```bash
docker run --rm -it --user $(id -u):$(id -g) -v $(pwd)/frontend:/workspace -w /workspace -p 4200:4200 node:22-alpine npm start -- --host 0.0.0.0
```

### Creating an Administrator
Superusers must be created interactively through Django's administrative CLI:
```bash
docker compose exec backend python manage.py createsuperuser
```

### Demo Data (DEBUG only)
To seed demo stages, users, customers, and leads in a development environment:
```bash
DEBUG=True python backend/manage.py seed_demo
```
*(Note: `seed_demo` automatically aborts with an error if `DEBUG=False`.)*

---

## Shared Redis Rate Limiting Verification

Login throttling is keyed on `(username, IP)` (5/min), IP (20/min), and username backstop (30/hour), backed by centralized Redis cache (`django.core.cache.backends.redis.RedisCache`):

> **Manual Check (Multiple Gunicorn Workers)**:
> When running the backend with 2 or more Gunicorn workers (e.g., `gunicorn config.wsgi:application --workers 4`), 5 failed login attempts from a given IP across different worker processes immediately trigger `429 Too Many Requests` on the 6th attempt. This verifies that login failure counters are shared atomically across Gunicorn worker processes in Redis, preventing per-process worker throttling bypass.

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

## OpenAPI Schema Synchronization

To ensure the committed OpenAPI schema (`schema.yml`) and TypeScript definitions (`schema.d.ts`) remain synchronized with the backend code:

```bash
# Check OpenAPI YAML schema
./scripts/check_schema.sh

# Regenerate and check TypeScript definitions
cd frontend && npm run generate:api && npm run check:api
```
