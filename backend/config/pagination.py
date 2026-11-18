from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """
    Standard pagination for list views:
    - Default page size: 20
    - Client configurable via 'page_size' query parameter
    - Enforced ceiling: maximum 100 items per page
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
