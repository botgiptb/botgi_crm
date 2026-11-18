from django.conf import settings


def get_client_ip(request) -> str:
    """
    Extract client IP safely respecting NUM_PROXIES setting.
    - If NUM_PROXIES <= 0 or HTTP_X_FORWARDED_FOR is missing: return REMOTE_ADDR.
    - If NUM_PROXIES > 0: take ips[-num_proxies].
    - If more proxies configured than entries in header: fallback to REMOTE_ADDR.
    """
    remote_addr = request.META.get("REMOTE_ADDR", "")
    num_proxies = getattr(settings, "NUM_PROXIES", 0)
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if num_proxies <= 0 or not x_forwarded_for:
        return remote_addr

    ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
    if not ips or num_proxies > len(ips):
        return remote_addr

    return ips[-num_proxies]
