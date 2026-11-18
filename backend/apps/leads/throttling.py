from rest_framework.throttling import SimpleRateThrottle

from apps.common.utils import get_client_ip


class CheckPhoneUserMinuteThrottle(SimpleRateThrottle):
    """Throttle phone checks to max 20 requests per minute per authenticated user."""

    scope = "check_phone_user_min"
    rate = "20/min"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"throttle_check_phone_user_min:{request.user.pk}"
        return None


class CheckPhoneUserDailyThrottle(SimpleRateThrottle):
    """Throttle phone checks to max 200 requests per day per authenticated user."""

    scope = "check_phone_user_day"
    rate = "200/day"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"throttle_check_phone_user_day:{request.user.pk}"
        return None


class CheckPhoneIPThrottle(SimpleRateThrottle):
    """Throttle phone checks per IP (max 30 requests per minute)."""

    scope = "check_phone_ip"
    rate = "30/min"

    def get_cache_key(self, request, view):
        client_ip = get_client_ip(request) or self.get_ident(request)
        return f"throttle_check_phone_ip:{client_ip}"
